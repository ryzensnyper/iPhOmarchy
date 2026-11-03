/* pmpmine.c — structural miner for the T8015 PMP (SMC) firmware.
 * Two linear passes (ARM then Thumb), extracting:
 *   - MOVW/MOVT pairs  -> 32-bit addresses referenced by code
 *   - BL targets        -> call inventory
 * Usage: pmpmine <bin> <base_va>
 * Build: gcc -O1 pmpmine.c -lcapstone -o pmpmine
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <capstone/capstone.h>

static uint8_t *slurp(const char *path, size_t *psz)
{
	FILE *f = fopen(path, "rb");
	if (!f) { perror("open"); return NULL; }
	fseek(f, 0, SEEK_END);
	*psz = ftell(f);
	fseek(f, 0, SEEK_SET);
	uint8_t *b = malloc(*psz);
	if (fread(b, 1, *psz, f) != *psz) { perror("read"); return NULL; }
	fclose(f);
	return b;
}

static void scan(csh h, const uint8_t *code_in, size_t sz, uint64_t va, const char *tag)
{
	cs_insn *ins = cs_malloc(h);
	const uint8_t *code = code_in;
	uint32_t movw_val[16] = {0};
	int movw_seen[16] = {0};
	uint64_t pc = va;
	while (sz) {
		if (!cs_disasm_iter(h, &code, &sz, &pc, ins)) {
			/* invalid byte: skip 1 byte and continue */
			code++; sz--; pc++;
			continue;
		}
		unsigned rd, imm;
		if (!strcmp(ins->mnemonic, "movw") &&
		    sscanf(ins->op_str, "r%u, #%x", &rd, &imm) == 2 && rd < 16) {
			movw_val[rd] = imm; movw_seen[rd] = 1;
		} else if (!strcmp(ins->mnemonic, "movt") &&
			   sscanf(ins->op_str, "r%u, #%x", &rd, &imm) == 2 &&
			   rd < 16 && movw_seen[rd]) {
			printf("ADDR %s @%#llx: r%u = %#010x\n", tag,
			       (unsigned long long)(ins->address - va), rd,
			       (imm << 16) | movw_val[rd]);
			movw_seen[rd] = 0;
		} else if (!strcmp(ins->mnemonic, "bl")) {
			unsigned long long t;
			if (sscanf(ins->op_str, "#%llx", &t) == 1)
				printf("BL %s @%#llx -> %#llx\n", tag,
				       (unsigned long long)(ins->address - va),
				       t - va);
		}
	}
	cs_free(ins, 1);
}

int main(int argc, char **argv)
{
	if (argc < 3) { fprintf(stderr, "usage: %s <bin> <base_va>\n", argv[0]); return 1; }
	csh ha, ht;
	if (cs_open(CS_ARCH_ARM, CS_MODE_ARM | CS_MODE_LITTLE_ENDIAN, &ha) ||
	    cs_open(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_LITTLE_ENDIAN, &ht)) {
		fprintf(stderr, "cs_open failed\n");
		return 1;
	}
	size_t sz;
	uint8_t *b1 = slurp(argv[1], &sz);
	if (!b1) return 1;
	uint64_t base = strtoull(argv[2], NULL, 0);
	printf("=== ARM pass ===\n");
	scan(ha, b1, sz, base, "arm");
	free(b1);
	uint8_t *b2 = slurp(argv[1], &sz);
	if (!b2) return 1;
	printf("=== THUMB pass ===\n");
	scan(ht, b2, sz, base + 1, "thumb");
	free(b2);
	return 0;
}
