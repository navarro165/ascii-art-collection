# clownfish-term

A live ASCII clownfish and sea anemone for your terminal, built as a screensaver. A simulated
clownfish swims around a swaying anemone, drawn entirely with text characters, and the scene
adapts to whatever size your terminal is, including when you resize it.

Press any key to quit.

## Run

Needs [uv](https://docs.astral.sh/uv/) (it fetches numpy for you) and a terminal with truecolor
(iTerm2, Ghostty, Kitty, WezTerm; most others work in 256-colour mode).

```bash
uv run --script clownfish_term.py
```

Or put it on your PATH and just type `clownfish`:

```bash
ln -s "$PWD/clownfish_term.py" ~/.local/bin/clownfish
```

Options: `--fps N` (default 15), `--speed X`, `--aspect A` (cell height/width; detected if your
terminal reports pixel size, otherwise 2.0), `--colors truecolor|256`, `--mouse-exit`,
`--seconds N`.

## How it adapts to size

The camera is pinned to the short axis of the terminal, so the fish keeps its detail (stripes, fin
rays, rim light) at any size, and wider or taller terminals simply show more of the reef.

`preview.py` renders frames to PNG for checking the look at different sizes (needs Pillow):

```bash
uv run --with numpy --with pillow python preview.py --size 200x60 --t 6 12
```

## Credit and licence

This is a derivative of the clownfish scene from **ASCII Lab** by Aleksandr Sapozhkov
([sapozhkov/ascii-lab-public](https://github.com/sapozhkov/ascii-lab-public), `01-clownfish`).
The fish model, anemone simulation and swimmer are theirs; this project strips the video export and
code panel, makes the grid size dynamic, and adds the live terminal renderer. The original
composition was inspired by a photo by Nhobgood on Wikimedia Commons.

The original repository does not state a licence, so no licence is granted here for the derived
parts. If you are the author and want this taken down or relicensed, open an issue.
