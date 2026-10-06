# CISO.ai — focused Streamlit implementation

Version 2 expands the same Streamlit app and its single workflow: enter or import 1–5 sanitized findings and business context, generate one AI draft, review/edit it, assign owners/dates/status, filter the action overview, and export. You can download and restore the working session without a database. It does not modify the earlier CISO.ai application or import its database.

## Upgrade your existing working app

Stop Streamlit with Ctrl+C. Copy the new code files and `tests/` from this package into your existing app folder, including the new `session_io.py`. Replace `.streamlit/config.toml` and `.streamlit/secrets.toml.example`. Keep your existing `.streamlit/secrets.toml` and `.venv` folder; the package contains no real key. Keep the exact Gemini model that worked for your project. Restart using `start-windows.ps1`.

## New workflow controls

- **CSV import:** open Import findings from CSV, download the blank template, fill 1–5 rows, upload, and click Import CSV findings. Save as UTF-8 CSV. Keep the five headers and exact enum values described in the app. Quoted commas and multiline observations are supported. Header-only templates cannot be imported until filled. The in-app limit is 500 KB; Streamlit rejects files over 1 MB before parsing.
- **Action tracking:** owner role/alias, optional target date and action status are human-entered. They never go to Gemini. Completed is self-reported, not verified. These fields appear in CSV, full-record JSON and session JSON.
- **Filters:** priority/status filters narrow the Action overview table only. Editors, review and exports still include all findings. Filters never delete actions or trigger an AI request.
- **Session save:** Download session JSON in the sidebar works even before generation, with partially entered findings. After generation, complete empty action text before saving. No automatic saving or cross-device database exists.
- **Session restore:** select a saved JSON file and click Restore uploaded session. A valid restore replaces current work, so download it first if needed. Your human edits and assignments return, but authorization/review checkboxes reset. No model call occurs. Earlier full-record JSON exports also load as unverified drafts. Uploaded files are not signed evidence or proof of AI authorship.
- **Input changes:** the previous plan becomes stale. Its edits remain in session downloads, but reviewed exports are blocked until the inputs match or a new draft is generated. A new generation clears previous edits/assignments; download first to keep them.
- **Invalid import:** parsing completes before state changes. A rejected file leaves current work intact. No file is executed, fetched by URL, or sent to the model on import.
- **Errors:** missing key, unavailable model, denied access, quota, network and malformed-output messages include next steps. No automatic model switch, retries, or paid-tier upgrade occurs.

## Run on Windows with VS Code

Use Python 3.10–3.14; the launcher now uses your installed `python` (including 3.14). Extract this folder, open it in VS Code, and open a PowerShell terminal here.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-windows.ps1
```

The script creates a virtual environment, installs dependencies, copies an example secrets file if needed, and starts Streamlit at http://localhost:8501. Package installation and AI generation need internet access. The application opens without a key, but generation is disabled until configured.

Create a key at https://aistudio.google.com/apikey and confirm your project’s free-tier status and available quota. Then, in VS Code, edit `.streamlit/secrets.toml` and set your own Google Gemini API key. Do not share the key in chat, screenshots or GitHub. An API account with model access and sufficient quota is required; this app does not use your ChatGPT login. The default model is `gemini-3.1-flash-lite`; the configured model must support Gemini generateContent structured output with the supplied JSON schema.

Alternatively, run manually:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
# Edit .streamlit/secrets.toml in VS Code before generating.
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

On macOS/Linux, use `python3 -m venv .venv`, `.venv/bin/python -m pip install -r requirements.txt`, copy the example secrets file, then `.venv/bin/python -m streamlit run app.py`.

## Deploy on Streamlit Community Cloud

1. Create your own GitHub repository and commit the contents of this folder. Keep `app.py` and `requirements.txt` at the repository root. `.gitignore` excludes the real secrets file, virtual environment and caches. If you upload through GitHub's web interface, manually exclude those files too: web uploads do not protect you using `.gitignore`.
2. In Streamlit Community Cloud, select **Create app**, choose your repository and branch, and set the entrypoint to `app.py`.
3. In Advanced settings select Python 3.12. Paste the following configuration into the secrets field, replacing the placeholder privately:

```toml
GEMINI_API_KEY = "PASTE_YOUR_KEY_HERE"
GEMINI_MODEL = "gemini-3.1-flash-lite"
MAX_CALLS_PER_DAY = "100"
```

4. Deploy and use the actual URL returned by Streamlit. No URL is supplied in this package because it has not been deployed to your account.
5. Check the link in a signed-out/incognito browser to confirm the intended public access. Generate a plan using authorized, sanitized data, review/edit, export, and check the downloaded files. Test on the presentation device.
6. Before presenting, record the real working flow using your own inputs, or prepare the configured local app as fallback. A local fallback also needs internet for the hosted model API. An actual recording of a successful run avoids that dependency.

No login, multiple roles, database, collectors, chat page, compliance certification or automatic fixes are implemented. No local Ollama endpoint is used. A cloud instance's localhost cannot reach the Ollama service on your Windows laptop.

## What the code does

| File | Responsibility |
| --- | --- |
| `app.py` | Input, consent, session state, review and export interface |
| `core.py` | Input/output validation, finding references, privacy reminders and CSV escaping |
| `session_io.py` | Bounded CSV/JSON parsing, draft restoration, tracking validation and filtering |
| `ai_client.py` | One fixed Google Gemini endpoint, prompt/schema, timeout/error handling and process call counter |
| `tests/` | Synthetic software fixtures and automated checks; not customer-research evidence |

User data goes from Streamlit server memory to Google Gemini when Generate is clicked. The model returns a structured plan. Local validation checks field types, size limits and exactly one output item per submitted finding. These checks cannot establish factual correctness. Each original AI item is retained separately from the human-reviewed version. Changing input blocks stale output; changing review fields blocks old exports until review is confirmed again.

The JSON download contains source input, original AI output, reviewed output, model configuration and timestamps. The CSV contains reviewed actions, owner/date/status and provenance fields. CSV text that could be interpreted as spreadsheet formulas is escaped. Downloaded outputs are product outputs, not ready-to-submit academic analysis.

## Privacy, reliability and operating limits

- Use only authorized, sanitized inputs. A small pattern detector warns about obvious email addresses, IP addresses and credentials; it is not a complete privacy filter.
- Inputs and outputs are not deliberately written to disk, a database, analytics or shared caches. They remain in the active session. The provider and host may process/retain data according to their policies. Google lists free-tier data as used to improve its products. Do not send sensitive business data; review the applicable Google terms.
- Clear session removes app working state; it cannot erase downloads or provider records. Reloading or losing the session may lose the plan.
- AI output can be wrong, biased, misleading or unsafe. Human validation is necessary. No actions are executed and no URLs supplied in findings are fetched.
- The app limits each request to five findings, bounds text lengths and output tokens, enforces a 30-second per-session cooldown, and uses a thread-safe process-level daily request count. The count resets on restart and can differ across processes. It is not robust abuse protection or a guaranteed spending cap. Configure appropriate provider-side limits/alerts and monitor public-demo usage.
- HTTP redirects are refused, error bodies and keys are not shown, and no automatic billable retries occur.
- The UI does not claim findings, interviews, measurements or customer validation were performed.

## Tests and verification

From this folder:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Linux equivalent: `.venv/bin/python -m unittest discover -s tests -v`.

Tests use mocked model responses and synthetic fixtures clearly marked as software tests. They also cover CSV imports, session round trips, legacy JSON, invalid uploads, tracking and filter behavior. They exercise validation, malformed/truncated/refused model responses, network errors, consent, privacy detection, review/export gating, stale data, session isolation and CSV safety. They do not prove live model quality, usability or customer value. See `VERIFICATION.txt` for checks actually run on this package.

## Authorship and course boundary

Code, tests, the technical README and configuration were generated with ChatGPT/Codex assistance. The user confirmed instructor approval before this implementation. The group must independently understand and verify the code, confirm the precise permission/disclosure requirements, and author its submitted content. This README is AI-generated technical documentation; do not submit it unchanged as student-authored coursework. Confirm whether it may serve as the required repository README, or replace it with a group-authored version.

No PRD, slide deck, customer research, personas, hypothesis evidence, roadmap, contribution assessment, or user-test results are supplied. The Phase 1 proposal was not available, so alignment with its selected opportunity has not been verified. The current inputs and output structure are implementation assumptions to validate using real research, not research-backed conclusions.

## Documentation used

- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
- https://docs.streamlit.io/develop/concepts/app-testing
- https://ai.google.dev/gemini-api/docs/generate-content/structured-output

Gemini free-tier eligibility, quotas and model availability may change. Check https://ai.google.dev/gemini-api/docs/pricing and your AI Studio project. Using a paid project can incur charges. If migrating from the previous package, replace the old OPENAI settings with GEMINI settings; the app does not reuse an OpenAI key.
