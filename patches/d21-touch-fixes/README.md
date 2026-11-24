# D21 touch fixes (Orchard `kernel/patches/` layout)

Four patches that make iPhone 8 Plus (D21) touch start reliably with the shared `apple_z2` driver.
Drop each file into the same path in an OrchardLinux/orchard checkout (base `eab974c`).

| Patch | What it fixes |
|---|---|
| `drivers/pinctrl/0099-…do-not-arm-masked-irq` | `apple_gpio_irq_set_type()` armed the pin while the IRQ core had it masked, so an asserted level interrupt stormed CPU0. This hung touchscreen module reloads (5 of 8). Generic for all Apple GPIO users. |
| `devices/t8015/0099-…touchclk-32k` | D21 touch reference clock set to 32768 Hz (ADT KLCT 0x8000), not the iPhone X's 24 MHz. |
| `drivers/input/0100-…boot-irq` | Keeps the D21 touch interrupt masked from the firmware wait-IRQ step until the first post-boot read. |
| `drivers/input/0108-…d9-retry` | Retries the 0xd9 surface-descriptor query, which a streaming frame can corrupt (1 in 76 starts). |

Validation on D21 (payload `c39e6e0e…`, default IRQ affinities): 5/5 fresh first boots and 10/10 module reloads delivered touch, with 0 hangs.
The earlier pinctrl-only build also passed 10/10 reloads.
