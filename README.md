# MWM Ai TFP Form Filler

FastAPI app for generating a completed editable TFP PDF from uploaded NRIC/ID, Benefits Illustration and supporting documents.

## Webpage fields
- Adviser Email *
- Product Type *
- NRIC / ID *
- Benefits Illustration *
- Client's expected Retirement Income (Yearly) with S$ prefix
- FA Signature
- Client Signature
- Any other documents

`*` denotes compulsory field.

## Output
- Completed editable TFP PDF only
- ZIP package containing the completed TFP
- Extraction audit JSON for internal checking

## Internal use
This form filler is intended strictly for use within Massive Wealth Management (MWM) and should not be shared outside the team.

## Railway start command

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Variables

```text
OPENAI_API_KEY=optional for future vision/AI extraction improvements
OPENAI_MODEL=gpt-4.1-mini
```

## Notes
This v1 uses deterministic extraction from PDFs/form fields where available and leaves uncertain fields editable/blank rather than inventing them.
