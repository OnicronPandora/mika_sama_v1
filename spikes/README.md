# Phase 0 spikes

Small, throwaway experiments that answer the go/no-go questions in Phase 0 of
[docs/implementation_plan.md](../docs/implementation_plan.md). Their results are recorded in that plan.

| Spike | Runs on | Question |
|-------|---------|----------|
| A: `spike_a_ollama` | Mac M1 | Can the M1 stream a reply and classify sentences at the same time? How long until the first sentence is approved? |
| B: `spike_b_tts` | Acer | Is GenieTTS faster than real time on the Acer's CPU? |
| C: `spike_c_live2d` | Acer | Does the Live2D model render in the browser, and can code drive `ParamMouthOpenY` (lipsync)? |

All commands run from the repo root.

---

## Spike A: Ollama on the Mac M1

### Setup (once)

```bash
conda create -p .conda -c conda-forge --override-channels python=3.11.9 pip -y
conda activate ./.conda
pip install -r spikes/spike_a_ollama/requirements.txt
ollama pull llama3.1:8b
```

### Run it twice: once with `OLLAMA_NUM_PARALLEL=1`, once with `2`

The setting belongs to the Ollama **server**, so Ollama has to be restarted after changing it.

If you use the Ollama menu-bar app:

```bash
launchctl setenv OLLAMA_NUM_PARALLEL 1
# Quit Ollama from the menu bar, then open it again
python spikes/spike_a_ollama/spike_a_ollama.py --label parallel-1

launchctl setenv OLLAMA_NUM_PARALLEL 2
# Quit Ollama from the menu bar, then open it again
python spikes/spike_a_ollama/spike_a_ollama.py --label parallel-2

launchctl unsetenv OLLAMA_NUM_PARALLEL   # back to the default; restart Ollama again
```

If you run the server in a terminal instead, quit the app first, then start `OLLAMA_NUM_PARALLEL=1 ollama serve`
(or `=2`) in a second terminal.

During the `parallel-2` run, keep Activity Monitor → Memory open. Yellow or red memory pressure means
two parallel slots are too much for this Mac.

Each run takes a few minutes and writes `spikes/spike_a_ollama/results/<label>.md` and `.json`.
Commit and push those files, or paste the two `.md` files into the chat.

Options: `--model`, `--prompts N` (1–5), `--num-predict` (default 150), `--host`.

---

## Spike B: GenieTTS on the Acer

### Setup (once)

```bash
conda create -p .conda -c conda-forge --override-channels python=3.11.9 pip -y
conda activate ./.conda
pip install -r spikes/spike_b_tts/requirements.txt
```

GenieTTS also needs its `GenieData` folder (about 390 MB) at `others/voice/GenieData`. Copy it from an
earlier project, or download it from Hugging Face with
`python -c "import genie_tts; genie_tts.download_genie_data()"` (this saves it to the current directory).

### Run

```bash
python spikes/spike_b_tts/spike_b_tts.py --label acer
```

Writes `spikes/spike_b_tts/results/<label>.md` and `.json`. The generated audio goes to
`spikes/spike_b_tts/out/` (git-ignored) so you can listen to it.

---

## Spike C: Live2D in the browser (Acer)

### Setup (once)

1. `npm install --prefix spikes/spike_c_live2d`
2. **Cubism Core** (Live2D Proprietary Software License, not on npm): download the **Cubism SDK for Web R5**
   from <https://www.live2d.com/en/sdk/download/web/> and copy `Core/live2dcubismcore.min.js` to
   `spikes/spike_c_live2d/public/`. The file is git-ignored.
   The CDN file at `cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js` is Core 5.1, which
   easy-live2d 1.0.0 rejects; it needs the R5 Core (version 6.0.1).
3. Run Spike B first (for the audio samples), then `npm run assets --prefix spikes/spike_c_live2d` to copy the
   Live2D model and the audio into `public/` (git-ignored).

### Run

```bash
npm run dev --prefix spikes/spike_c_live2d
```

Open <http://localhost:5173>. The panel buttons hold the mouth open or closed, run a sine wave, play a motion,
and play a Spike B sentence with lipsync computed from the audio volume.
