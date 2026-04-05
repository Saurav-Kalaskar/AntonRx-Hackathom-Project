# Time-to-Therapy
Prior Authorization Copilot
Stitch Project

## Required Aesthetics
* **Theme**: Crisp whites, soft teals, and slate blues.
* **Component Library**: Enforce strictly shadcn-ui components throughout. No arbitrary custom components if a shadcn equivalent exists (e.g. use standard Dialog, Button, Table, Card, Badge).
* **Typography**: Clean, professional medical software typography (Inter/Roboto).
* **Alerts & Exceptions**: Reserve vibrant amber (#ffbf00) or soft coral (#f88379) *EXCLUSIVELY* for "Meaningful Change" alerts, step-therapy blockers, and AI confidence score overlays.
* **Layout**: Information dense but with minimized cognitive load. 

## 6. Design System Notes for Stitch Generation
**DESIGN SYSTEM (REQUIRED for all Stitch Prompts):**
You are designing enterprise healthcare software.
1. Strictly utilize shadcn-ui elements (Cards, Tables, Badges, Tabs).
2. The primary color palette must use crisp whites (background), soft teals (highlights/primary actions), and slate blues (borders/secondary elements).
3. Do not use generic reds/greens for status. Use amber/soft coral specifically for required "Step-Therapy" blockers or AI confidence warnings.
4. Maintain a zero-friction experience: No login barriers, instant load into the application core workflow.
5. All outputs and modal windows must display high-fidelity, polished, and rounded aesthetic boundaries (`rounded-lg` or `md`).
