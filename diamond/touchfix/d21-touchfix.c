/*
 * d21-touchfix.c — D21 (iPhone10,2) stale-contact fixer daemon.  v3 2026-11-04.
 *
 * WHY THIS EXISTS (project: ~/omarchy-iphone, traceability: tools/README-touchfix.md)
 *
 * The Z2 controller holds contacts ALIVE for seconds without ever reporting a lift
 * (measured 2026-11-02 night: a contact held t=11.27-24.72 s / 73 frames, states [3,4],
 * no state==0 lift; captures/combo-KEY5.txt). While such a stale contact is held, every
 * NEW physical tap arrives on a second slot -> libinput sees two fingers -> the app
 * (e.g. omacalc) treats it as a multi-finger gesture and discards the click.
 * Measured: 14 BTN_TOUCH downs reached the desktop, only 4 clicks reached the app.
 *
 * FIX (userspace, zero kernel/dance risk): sit between the driver and libinput.
 *   read /dev/input/event1 -> apply three rules -> write a uinput virtual device:
 *
 *   RULE 0 (thin-sliver gate, v3 2026-11-04): a FRESH contact whose NARROWER touch
 *   dimension (min of ABS_MT_TOUCH_MAJOR/MINOR) is below slim_min is not a finger -
 *   it is the bottom-band blob sliver or a hover artifact.  Measured separation
 *   (captures/combo-TLOW2-e1.txt, HEALTHY roll): every artifact downs thin
 *   (blob slivers 1033x153 / 824x148, hover blip 257x122 - min 122..157) while every
 *   real finger contact is fat in BOTH dimensions (min 274..998, drags 787+).
 *   Mechanisms killed: (a) the blob's 1-frame pressure spikes (pr 185-369) passing
 *   pres_min -> solo ghost clicks in the bottom-centre zone; (b) hover artifacts
 *   downs 0-50 ms before a real tap -> the real tap becomes contact #2 -> the
 *   compositor discards the pair as a two-finger gesture (the "tap did nothing" quirk,
 *   measured on the top-right reference taps).  The cancel/re-zombie happens in the
 *   SAME evdev frame as the down (TID k ... TID -1 before SYN), so libinput never
 *   sees the contact.  A contact that fattens within resurrect_ms gets its down
 *   re-emitted (safety for steep-angle fingertip arrivals).  slim_min=0 disables.
 *
 *   RULE 1 (stale release): when a NEW contact appears (ABS_MT_TRACKING_ID >= 0) while
 *   another slot has been continuously held longer than STALE_MS, synthesise that
 *   stale slot's lift (ABS_MT_TRACKING_ID = -1) BEFORE the new contact is forwarded.
 *   The fresh tap then lands as the ONLY finger down = a clean single-finger click.
 *
 *   RULE 2 (palm arbitration): when a contact's touch area (touch_major x
 *   touch_minor) crosses PALM_AREA while ANOTHER contact is down, synthesise its lift
 *   immediately and zombie it. This is iOS's multi-touch arbitration: the controller
 *   reports the user's palm-edge resting near the bottom bezel as REAL touches
 *   that flash through the driver's 8-frame latch as 1-3-frame fragments; each
 *   fragment occupies a second slot and the app discards the concurrent real tap as a
 *   two-finger gesture. A palm-scale area only arbitrates away when a finger is down;
 *   solo palm rests are untouched, and finger-scale concurrent contacts pass.
 *   (NOTE: this runs on the TOUCH dimensions; the v3 sliver gate is what actually
 *   catches the blob - see RULE 0.)
 *
 *   BTN_TOUCH is OWNED from v3: computed from the number of live forwarded slots at
 *   each SYN, the driver's own BTN_TOUCH is dropped.  A gated phantom can then never
 *   hold the button down, and a suppressed-only frame forwards as a clean "nothing
 *   touched" frame instead of BTN_TOUCH=1-with-no-contacts.
 *
 *   Long-press is preserved: no rule fires while no new contact/palm-crossing occurs.
 *   Drag is preserved: smooth movement is not a new contact. Controller updates for a
 *   force-released slot are forwarded harmlessly: libinput ignores position events on
 *   a slot whose tracking id is -1. When the controller finally lifts the zombie
 *   (TID = -1) the passthrough forwards it as a no-op; if it re-uses the slot for a
 *   genuinely new contact, the fresh down resets everything.
 *
 * Deploy: tools/README-touchfix.md (build via the orchard container, scp, systemd unit
 * + udev rule that benches the raw device with LIBINPUT_IGNORE_DEVICE).
 *
 * Rollback: systemctl disable --now d21-touchfix; remove the udev rule; udevadm trigger.
 * (v3 rollback within the daemon: run with -s 0 = gate off, v2 behaviour + owned BTN.)
 * The raw device path is untouched by the daemon (read-only).
 *
 * Build: aarch64-linux-gnu-gcc -static -O2 -o d21-touchfix d21-touchfix.c
 *        (orchard-hardware-recovery-tools container has the cross-gcc)
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <time.h>
#include <sys/ioctl.h>
#include <linux/input.h>
#include <linux/uinput.h>

#define NSLOTS 16
#define DEF_STALE_MS 1500
#define DEF_PALM_AREA 2500000   /* palm floor on TOUCH dims: fingers are fat, see RULE 0 */
#define DEF_SLIM_MIN 220        /* RULE 0: min(TOUCH_MAJ,TOUCH_MIN) below this = artifact
                                 * (measured: artifacts <=157, real fingers >=274) */
#define RESURRECT_MS 150        /* a cancelled thin contact may re-down if it fattens
                                 * within this window (steep-angle fingertip safety) */

static volatile sig_atomic_t run = 1;
static void on_term(int s) { (void)s; run = 0; }

static long long ms_now(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

struct slot {
	int tid;                /* -1 = up (OUR forwarded view: thin-gated slots sit at -1) */
	int dtid;               /* the driver's tracking id for this slot (-1 = up) */
	long long down_ms;      /* when the current tracking id appeared */
	int stale;              /* force-released by us; zombie until real lift */
	int thin;               /* RULE 0: gated at arrival; zombie until fatten or lift */
	int tmaj;               /* last touch_major seen for this slot */
	int tmin;               /* last touch_minor */
	int max_area;           /* max touch area seen this contact life */
};

static int uf = -1;
static void emit(int type, int code, int val)
{
	struct input_event e;
	memset(&e, 0, sizeof(e));
	gettimeofday(&e.time, NULL);
	e.type = type; e.code = code; e.value = val;
	if (write(uf, &e, sizeof(e)) != sizeof(e))
		perror("uinput write");
}

int main(int argc, char **argv)
{
	long long stale_ms = DEF_STALE_MS;
	long long palm_area = DEF_PALM_AREA;
	long long slim_min = DEF_SLIM_MIN;
	const char *src = "/dev/input/event1";
	int i, fd, cur_slot = 0;
	int declared[ABS_MAX + 1] = { 0 };
	struct slot slot[NSLOTS];
	struct input_absinfo ai;
	static struct input_event buf[64];
	int n, j;
	int live = 0, last_btn = 0;   /* owned BTN_TOUCH state */

	for (i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "-t") && i + 1 < argc)
			stale_ms = atoll(argv[++i]);
		else if (!strcmp(argv[i], "-a") && i + 1 < argc)
			palm_area = atoll(argv[++i]);
		else if (!strcmp(argv[i], "-A"))
			palm_area = 0;   /* -A: disable palm arbitration */
		else if (!strcmp(argv[i], "-s") && i + 1 < argc)
			slim_min = atoll(argv[++i]);   /* -s 0: disable sliver gate */
		else
			src = argv[i];
	}
	signal(SIGTERM, on_term);
	signal(SIGINT, on_term);

	fd = open(src, O_RDONLY);
	if (fd < 0) { perror("open source"); return 1; }
	/* the node can vanish when the module reloads; libinput just sees no
	 * touch for that window either way, and systemd restarts us */
	fcntl(fd, F_SETFL, 0);

	uf = open("/dev/uinput", O_WRONLY | O_NONBLOCK);
	if (uf < 0) { perror("open /dev/uinput (modprobe uinput?)"); return 1; }

	/* mirror the source device's ABS ranges so libinput sees an equivalent
	 * touchscreen. Only codes the source ACTUALLY declares are declared here —
	 * a code absent upstream (e.g. ABS_MT_PRESSURE on this driver) must not be
	 * declared with an empty range, that fails the uinput setup with EINVAL.
	 * libinput's touchscreen path needs X/Y/SLOT/TID + BTN_TOUCH; TOUCH_MAJOR/
	 * MINOR are declared when present (the palm-arbitration rule needs them).
	 * Uses the modern UI_DEV_SETUP/UI_ABS_SETUP interface (the legacy
	 * uinput_user_dev write returns EINVAL on this kernel). */
	{
		static const int codes[] = {
			ABS_MT_SLOT, ABS_MT_POSITION_X, ABS_MT_POSITION_Y,
			ABS_MT_TRACKING_ID, ABS_MT_TOUCH_MAJOR, ABS_MT_TOUCH_MINOR,
		};
		int nc = sizeof(codes) / sizeof(codes[0]);
		struct uinput_setup us;
		if (ioctl(uf, UI_SET_EVBIT, EV_SYN) ||
		    ioctl(uf, UI_SET_EVBIT, EV_KEY) ||
		    ioctl(uf, UI_SET_EVBIT, EV_ABS) ||
		    ioctl(uf, UI_SET_KEYBIT, BTN_TOUCH) ||
		    ioctl(uf, UI_SET_PROPBIT, INPUT_PROP_DIRECT)) {
			perror("uinput bit setup");
			return 1;
		}
		for (i = 0; i < nc; i++) {
			struct uinput_abs_setup as;
			int lo = 0, hi = 0;
			int have = 0;
			if (codes[i] == ABS_MT_TRACKING_ID) {
				lo = -1; hi = 65535; have = 1;
			} else if (ioctl(fd, EVIOCGABS(codes[i]), &ai) == 0 &&
				   ai.maximum > ai.minimum) {
				lo = ai.minimum; hi = ai.maximum; have = 1;
			}
			if (!have)
				continue;   /* not declared upstream: drop its events */
			if (codes[i] == ABS_MT_SLOT && hi < NSLOTS - 1) hi = NSLOTS - 1;
			declared[codes[i]] = 1;
			memset(&as, 0, sizeof(as));
			as.code = codes[i];
			as.absinfo.minimum = lo;
			as.absinfo.maximum = hi;
			if (ioctl(uf, UI_ABS_SETUP, &as)) {
				fprintf(stderr, "touchfix: UI_ABS_SETUP %#x", codes[i]);
				perror("");
				return 1;
			}
			fprintf(stderr, "touchfix: ABS %#x range %d..%d\n", codes[i], lo, hi);
		}
		memset(&us, 0, sizeof(us));
		snprintf(us.name, UINPUT_MAX_NAME_SIZE, "d21-touchfix virtual touchscreen");
		us.id.bustype = BUS_VIRTUAL;
		us.id.vendor = 0x0001;
		us.id.product = 0x0001;
		us.id.version = 1;
		us.ff_effects_max = 0;
		if (ioctl(uf, UI_DEV_SETUP, &us) || ioctl(uf, UI_DEV_CREATE)) {
			perror("uinput dev setup/create");
			return 1;
		}
	}
	fprintf(stderr, "touchfix: v3 virtual device created; stale_ms=%lld palm_area=%lld slim_min=%lld; src=%s\n",
		stale_ms, palm_area, slim_min, src);

	memset(slot, 0, sizeof(slot));
	for (i = 0; i < NSLOTS; i++) slot[i].tid = -1;

	while (run) {
		n = (int)read(fd, buf, sizeof(buf));
		if (n <= 0) {
			if (!run) break;
			fprintf(stderr, "touchfix: source gone (%m); exiting for restart\n");
			break;
		}
		for (j = 0; j < n / (int)sizeof(struct input_event); j++) {
			struct input_event *e = &buf[j];
			switch (e->type) {
			case EV_SYN:
				/* BTN_TOUCH is ours: live = forwarded non-stale slots.
				 * (Thin-gated slots sit at tid -1 in our view, so a
				 * phantom-only frame forwards as a clean no-touch.) */
				live = 0;
				for (i = 0; i < NSLOTS; i++)
					live += (slot[i].tid >= 0);
				if (last_btn != (live > 0)) {
					last_btn = (live > 0);
					emit(EV_KEY, BTN_TOUCH, last_btn);
				}
				emit(EV_SYN, SYN_REPORT, 0);
				break;
			case EV_KEY:
				/* driver BTN_TOUCH dropped: BTN state is owned above */
				break;
			case EV_ABS:
				if (e->code == ABS_MT_SLOT) {
					if (e->value >= 0 && e->value < NSLOTS)
						cur_slot = e->value;
					if (declared[ABS_MT_SLOT])
						emit(EV_ABS, ABS_MT_SLOT, cur_slot);
				} else if (e->code == ABS_MT_TRACKING_ID) {
					if (e->value >= 0) {
						/* NEW contact: bench stale held slots first */
						long long now = ms_now();
						int s;
						for (s = 0; s < NSLOTS; s++) {
							if (s == cur_slot || slot[s].tid < 0 || slot[s].stale)
								continue;
							if (now - slot[s].down_ms > stale_ms) {
								if (declared[ABS_MT_SLOT])
									emit(EV_ABS, ABS_MT_SLOT, s);
								emit(EV_ABS, ABS_MT_TRACKING_ID, -1);
								fprintf(stderr,
									"touchfix: force-released stale slot %d "
									"(tid %d, held %lld ms) for new tid %d\n",
									s, slot[s].tid, now - slot[s].down_ms,
									e->value);
								slot[s].tid = -1;
								slot[s].stale = 1;
							}
						}
						slot[cur_slot].tid = e->value;
						slot[cur_slot].dtid = e->value;
						slot[cur_slot].down_ms = now;
						slot[cur_slot].stale = 0;
						slot[cur_slot].thin = 0;
						slot[cur_slot].tmaj = 0;
						slot[cur_slot].tmin = 0;
						slot[cur_slot].max_area = 0;
					} else {
						slot[cur_slot].tid = -1;
						slot[cur_slot].dtid = -1;
						slot[cur_slot].stale = 0;
						slot[cur_slot].thin = 0;
						slot[cur_slot].max_area = 0;
					}
					emit(EV_ABS, ABS_MT_TRACKING_ID, e->value);
				} else if (e->code == ABS_MT_TOUCH_MAJOR ||
					   e->code == ABS_MT_TOUCH_MINOR) {
					if (declared[e->code]) {
						long long area;
						if (e->code == ABS_MT_TOUCH_MAJOR)
							slot[cur_slot].tmaj = e->value;
						else
							slot[cur_slot].tmin = e->value;
						area = (long long)slot[cur_slot].tmaj *
						       slot[cur_slot].tmin;
						if (area > slot[cur_slot].max_area)
							slot[cur_slot].max_area = (int)area;

						/* RULE 0 (v3): thin-sliver gate.  Judge only
						 * fresh contacts (<= RESURRECT_MS old): a
						 * sliver arriving is the blob / a hover
						 * artifact - cancel its down in this same
						 * frame so libinput never sees it.  A held
						 * contact going thin later is a lifting
						 * finger - let it ride. */
						if (slim_min > 0 && slot[cur_slot].dtid >= 0) {
							int lo = slot[cur_slot].tmaj < slot[cur_slot].tmin ?
								 slot[cur_slot].tmaj : slot[cur_slot].tmin;
							long long now = ms_now();
							if (!slot[cur_slot].thin && lo < slim_min &&
							    slot[cur_slot].tid >= 0 &&
							    now - slot[cur_slot].down_ms <= RESURRECT_MS) {
								if (declared[ABS_MT_SLOT])
									emit(EV_ABS, ABS_MT_SLOT, cur_slot);
								emit(EV_ABS, ABS_MT_TRACKING_ID, -1);
								fprintf(stderr,
									"touchfix: gated thin slot %d "
									"(tid %d, shape %dx%d)\n",
									cur_slot, slot[cur_slot].dtid,
									slot[cur_slot].tmaj,
									slot[cur_slot].tmin);
								slot[cur_slot].tid = -1;
								slot[cur_slot].thin = 1;
							} else if (slot[cur_slot].thin && lo >= slim_min &&
								   now - slot[cur_slot].down_ms <= RESURRECT_MS) {
								/* fattened in time: re-down */
								if (declared[ABS_MT_SLOT])
									emit(EV_ABS, ABS_MT_SLOT, cur_slot);
								emit(EV_ABS, ABS_MT_TRACKING_ID,
								     slot[cur_slot].dtid);
								fprintf(stderr,
									"touchfix: resurrected fattened slot %d "
									"(tid %d, shape %dx%d)\n",
									cur_slot, slot[cur_slot].dtid,
									slot[cur_slot].tmaj,
									slot[cur_slot].tmin);
								slot[cur_slot].tid = slot[cur_slot].dtid;
								slot[cur_slot].thin = 0;
							}
						}

						/* RULE 2: palm arbitration.  A contact that
						 * grows to palm scale while ANOTHER contact
						 * is held is the user's palm edge - lift it
						 * immediately so the concurrent real tap
						 * stays single-finger. */
						if (palm_area > 0 && area >= palm_area &&
						    !slot[cur_slot].stale &&
						    slot[cur_slot].tid >= 0) {
							int s, other = 0;
							for (s = 0; s < NSLOTS && !other; s++)
								other = (s != cur_slot &&
									 slot[s].tid >= 0 &&
									 !slot[s].stale);
							if (other) {
								if (declared[ABS_MT_SLOT])
									emit(EV_ABS, ABS_MT_SLOT,
									     cur_slot);
								emit(EV_ABS, ABS_MT_TRACKING_ID, -1);
								fprintf(stderr,
									"touchfix: arbitrated palm "
									"slot %d (tid %d, area %lld)\n",
									cur_slot, slot[cur_slot].tid,
									area);
								slot[cur_slot].tid = -1;
								slot[cur_slot].stale = 1;
							}
						}
						emit(EV_ABS, e->code, e->value);
					}
					/* undeclared major/minor: dropped */
				} else if (declared[e->code]) {
					emit(EV_ABS, e->code, e->value);   /* x/y */
				}
				break;
			default:
				break;  /* drop anything unexpected */
			}
		}
	}

	if (uf >= 0) { ioctl(uf, UI_DEV_DESTROY); close(uf); }
	close(fd);
	fprintf(stderr, "touchfix: exited\n");
	return 0;
}
