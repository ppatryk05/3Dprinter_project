# Symulator Drukarki 3D — Zadanie 6

Animowana wizualizacja pracy drukarki 3D z pełnym modelem kinematycznym, termicznym i wizualnym.

---

## Wymagania

- **Python 3.11 lub nowszy** (projekt testowany na 3.14)
- **Git** (opcjonalnie, do klonowania repo)

Sprawdź wersję Pythona:
```
python --version
```

---

## Instalacja krok po kroku

### 1. Pobierz / sklonuj projekt

Jeśli masz repo na GitHubie:
```
git clone <adres-repo>
cd 3Dprinter_project
```

Albo po prostu skopiuj folder projektu i otwórz go w terminalu.

### 2. (Zalecane) Utwórz wirtualne środowisko

```
python -m venv .venv
```

Aktywacja na **Windows**:
```
.venv\Scripts\activate
```

Aktywacja na **macOS / Linux**:
```
source .venv/bin/activate
```
Jesli PowerShell blokuje skrypty, wykonaj raz:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 3. Zainstaluj zależności

```
pip install -r requirements.txt
```

> Pierwsze uruchomienie może potrwać 2–5 minut — pobierane są duże pakiety (PyQt6, pyqtgraph, numba itp.).

---

## Uruchomienie

### Opcja A — przez Cursor / VS Code (kliknij Run)

Otwórz plik `run.py` i kliknij przycisk **Run** (▶) — aplikacja uruchomi się od razu.

### Opcja B — z terminala

```
python run.py
```

lub:

```
python src/main.py
```

lub jako moduł:

```
python -m src.main
```

---

## Obsługa programu

| Akcja | Co robi |
|---|---|
| **Załaduj G-code** | Otwiera plik `.gcode` do symulacji |
| **Play / Pauza** lub `Spacja` | Startuje / zatrzymuje odtwarzanie |
| **Restart** | Wraca do początku symulacji |
| **Suwak Prędkość** | Reguluje ile kroków/klatkę (1× – 50×) |
| **Zapisz sesję (JSON)** | Eksportuje przebieg symulacji do pliku |

### Sterowanie widokiem 3D

| Akcja | Sterowanie |
|---|---|
| Obracanie widoku | Lewy przycisk myszy + przeciągnij |
| Zoom | Scroll myszki |
| Przesuwanie widoku | Prawy przycisk myszy + przeciągnij |

---

## Struktura projektu

```
3Dprinter_project/
├── run.py                  ← punkt startowy (kliknij Run tutaj)
├── requirements.txt
├── examples/
│   └── sample.gcode        ← przykładowy plik G-code (5 warstw)
├── src/
│   ├── main.py             ← inicjalizacja aplikacji Qt
│   ├── core/
│   │   ├── gcode_parser.py ← parsowanie G-code
│   │   ├── kinematics.py   ← model ruchu osi X/Y/Z
│   │   ├── thermal_model.py← temperatura dyszy i stołu
│   │   └── material_model.py← odkładanie filamentu
│   ├── sim/
│   │   ├── simulator.py    ← pipeline symulacji + interpolacja
│   │   └── collision.py    ← walidacja granic ruchu
│   ├── render/
│   │   └── scene3d.py      ← viewport 3D (pyqtgraph.opengl)
│   ├── ui/
│   │   └── main_window.py  ← okno główne (PyQt6)
│   └── io/
│       └── session_replay.py← zapis/odczyt sesji JSON
└── docs/
    └── IMPLEMENTATION.md   ← opis architektury
```

---

## Własny plik G-code

Możesz załadować dowolny plik `.gcode` przez przycisk **Załaduj G-code**.  
Obsługiwane komendy: `G0`, `G1`, `M104`, `M109`, `M140`, `M190`.

Przykład prostego pliku:
```gcode
M104 S205        ; temperatura dyszy
M140 S60         ; temperatura stołu
G1 Z0.2 F600
G1 X100 Y100 F9000
G1 X200 Y100 E5.0 F4800
G1 X200 Y200 E10.0
```

---

## Problemy

**Program się nie uruchamia po instalacji?**
- Upewnij się że środowisko wirtualne jest aktywne (`pip list` powinien pokazać `PyQt6`)
- Sprawdź wersję Pythona: musi być ≥ 3.11

**Okno jest czarne lub nie widać drukarki?**
- Upewnij się że sterowniki karty graficznej obsługują OpenGL 2.0+
- Spróbuj zaktualizować sterowniki GPU
