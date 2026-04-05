---
page: history
---
A "History" view for the Time-to-Therapy Copilot. This view allows users to see past drafted PA requests.

**DESIGN SYSTEM (REQUIRED for all Stitch Prompts):**
You are designing enterprise healthcare software.
1. Strictly utilize shadcn-ui elements (Cards, Textareas, Buttons, Avatars, ScrollArea).
2. The primary color palette must use crisp whites (background), soft teals (highlights/primary actions), and slate blues (borders/secondary elements).
3. Do not use generic reds/greens for status. Use amber/soft coral specifically for required "Step-Therapy" blockers or AI confidence warnings.
4. Maintain a zero-friction experience: No login barriers, instant load into the application core workflow.
5. All outputs and modal windows must display high-fidelity, polished, and rounded aesthetic boundaries (`rounded-lg` or `md`).

**Page Structure:**
1. A clean Top Navigation Bar with the logo "Time-to-Therapy" and Navigation links to "Matrix" and "Copilot".
2. A main area featuring a List or Data Table of past PA requests. Columns: Date, Patient, Drug, Payer, Status (Pending, Approved, Denied).
3. A detail pane (sheet or side card) that opens when a row is clicked, showing the exact PA Draft and Payer Rules applied.
4. Keep the same sticky Bottom Navigation Bar as copilot.html.
