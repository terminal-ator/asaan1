# Ordex contributor guidance

## Current phase

- The PWA captures orders; staff bill them by hand in Marg ERP.
- The console prepares printed order slips and line-item CSV exports. It must
  not assign invoice numbers or post dispatch stock until auto-billing is built.
- `OrderInvoiceForm`, `invoice_detail`, `invoice_json`, `invoice_excel`, and
  `einvoice_upload` are parked for that future phase: keep the code and models,
  but do not link them from the console UI.

## Forms and console UI

- Always use a tabbed interface for long create/edit forms.
- Group related fields into meaningful tabs (for example: details, pricing, logistics, media, and tax).
- Use a two-column responsive layout on large screens and a single-column layout on small screens.
- Keep each tab focused so users do not need to scroll through a long uninterrupted form.
- Preserve clear validation messages and visible save/cancel actions across the form.

