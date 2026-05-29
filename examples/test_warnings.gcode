; test_warnings.gcode – triggers cold-extrusion and soft-limit warnings
; Load this file and watch the issue bar at the top of the sidebar.

G28            ; home

; ── Test 1: Cold extrusion (nozzle at room temperature, E increases) ────────
; Nozzle is ~25°C here – simulator should block E and emit warning.
G1 X50 Y50 Z0.2 E5.0 F1200   ; cold move – E blocked, warning shown

; ── Test 2: Heat up and verify extrusion resumes ────────────────────────────
M104 S200
M109 S200      ; wait – watch temperature rise in the chart
G1 X100 Y50 E10.0 F1200      ; now hot – extrusion visible (orange)
G1 X100 Y100 E15.0
G1 X50  Y100 E20.0
G1 X50  Y50  E25.0

; ── Test 3: Soft-limit violations ───────────────────────────────────────────
; X and Y exceed 220 mm build area – clamped + alarm
G1 X250 Y50  E30.0 F3000     ; X > 220 → X soft-limit hit
G1 X100 Y260 E35.0            ; Y > 220 → Y soft-limit hit
G1 X100 Y100 E40.0            ; normal

; ── Test 4: Z soft limit ────────────────────────────────────────────────────
G1 Z260 F600                  ; Z > 250 → Z soft-limit hit
G1 Z10  F600                  ; back to safe range
G1 X110 Y110 E45.0

M104 S0
M140 S0
