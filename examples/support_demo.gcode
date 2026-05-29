; Support demo – tests ;TYPE:SUPPORT colour routing
; Generated for 3D Printer Simulator

M104 S200    ; set nozzle target
M140 S60     ; set bed target
G28          ; home all axes
M109 S200    ; wait for nozzle
M190 S60     ; wait for bed

; --- First layer: model perimeter (orange) ---
;TYPE:PERIMETER
G1 Z0.2 F600
G1 X10 Y10 E0 F3000
G1 X210 Y10  E10.0 F3000
G1 X210 Y210 E20.0
G1 X10  Y210 E30.0
G1 X10  Y10  E40.0

; --- Support structure (blue) ---
;TYPE:SUPPORT
G1 X30 Y30 E40.0 F3000
G1 X80 Y30 E44.0
G1 X80 Y80 E48.0
G1 X30 Y80 E52.0
G1 X30 Y30 E56.0

G1 X130 Y130 E56.0 F6000
G1 X180 Y130 E60.0
G1 X180 Y180 E64.0
G1 X130 Y180 E68.0
G1 X130 Y130 E72.0

; --- Back to model (orange) ---
;TYPE:SOLID-INFILL
G1 X10 Y10 E72.0 F6000
G1 X210 Y210 E82.0 F3000
G1 X210 Y10  E92.0
G1 X10  Y210 E102.0

; Done
M104 S0
M140 S0
