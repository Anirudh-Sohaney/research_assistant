# Overlay UI Subsystem

## 1. Final Deliverable
A non-intrusive, floating visual overlay management subsystem (`overlay_ui.overlay.OverlayUIManager`) providing:
- Floating popup card display anchored to active selection coordinates (`display_popup_card`).
- Screen boundary clamping and vertical collision flipping (e.g. flipping above text when near bottom edge).
- Dynamic, flicker-free content updating (`update_popup_content`).
- Immediate and graceful popup dismissal (`dismiss_popup`).
- Keystroke-driven selection and action dispatching (`[1]`–`[8]` number badge selection, `[Esc]` dismissal, `[Enter]` submission).
- Strongly typed card payload and event data models (`PopupCardPayload`, `PopupItem`, `ScreenRect`, `PopupHandle`, `PopupActionEvent`).

## 2. Algorithm Used
- **Anchor Coordinate Clamping & Collision Flipping**:
  1. Calculate preferred vertical coordinate below selection anchor: $y_{pref} = y_{anchor} + h_{anchor} + \delta_y$ (where $\delta_y = 8\text{px}$).
  2. If $y_{pref} + h_{popup} > H_{screen} - \text{margin}$, test top placement: $y_{alt} = y_{anchor} - h_{popup} - \delta_y$.
  3. If $y_{alt} < \text{margin}$, clamp vertical position: $y = \max(\text{margin}, H_{screen} - h_{popup} - \text{margin})$; otherwise, set $y = y_{alt}$.
  4. Compute horizontal coordinate aligned with selection start: $x_{pref} = x_{anchor}$.
  5. If $x_{pref} + w_{popup} > W_{screen} - \text{margin}$, clamp to right margin: $x = W_{screen} - w_{popup} - \text{margin}$. If $x < \text{margin}$, clamp to $\text{margin}$.
  6. Return clamped screen bounding rectangle `ScreenRect(x, y, w, h)`.
- **Progressive Disclosure & Keyboard Navigation**:
  1. Map index keys (`[1]`–`[8]`) directly to displayed item IDs for instantaneous word swap and injection without focus loss.
  2. Handle `[Esc]` to immediately dismiss the popup and return foreground focus to the editor.

## 3. Description
The `overlay_ui` subsystem is the visual companion layer for the research assistant. It floats contextual cards (definitions, synonyms, academic paper recommendations, evidence stances, and codebase summaries) directly next to the author's highlighted text across Microsoft Word, Google Docs, LaTeX editors, and Markdown applications. By employing non-activating window styles and intelligent boundary clamping, it provides immediate contextual insights and rapid single-keystroke selection while leaving the author's typing focus completely undisturbed.
