# User requirements

This document lists what the Validated Study Tracker must do. It was written before
any code, and each requirement is testable: every one is verified by at least one
automated test named after it (`test_req_007_...` for REQ-007), and the
[traceability matrix](traceability_matrix.md) is generated from the test results on
every CI run.

The design is *inspired by* regulated-software practice, in particular the audit-trail
expectations of FDA 21 CFR Part 11 (§11.10(e)) and the ALCOA+ data-integrity principles
(attributable, contemporaneous, original, accurate). It is a portfolio project. It has
not been validated and makes no claim of compliance with Part 11 or any other
regulation. See [Out of scope](#out-of-scope).

## Definitions

| Term | Meaning |
|---|---|
| **Study** | A clinical study record: study ID, title, phase, sponsor, target enrollment, site count and status. |
| **User** | A person known to the system by a unique username. |
| **Change** | Creating a study, editing its fields, changing its status, or deleting it. |
| **Reason for change** | Free text, entered by the user, explaining why a change was made. |
| **Audit entry** | One row in the audit trail describing one change to one field. |

**Phases:** Early Phase 1, Phase 1, Phase 1/2, Phase 2, Phase 2/3, Phase 3, Phase 4,
Not applicable.

**Statuses:** Planned, Recruiting, Active not recruiting, Suspended, Completed,
Terminated, Withdrawn. Completed, Terminated and Withdrawn are *final*.

## Requirements

### Study records

**REQ-001 Create a study.**
An identified user can create a study by entering its study ID, title, phase, sponsor,
target enrollment and site count. A new study always starts in status *Planned*.
- A valid submission creates exactly one study, with the values entered.
- The new study's status is Planned, and no status can be chosen at creation.

**REQ-002 Required fields.**
Study ID, title, phase, sponsor, target enrollment and site count are required. A
create or edit with any of them missing or blank is rejected, nothing is saved, and
the message names each missing field.

**REQ-003 Field validation.**
Values must be well formed. A create or edit with an invalid value is rejected and
nothing is saved:
- the study ID is 3 to 20 characters, using only letters, digits and hyphens, starting
  with a letter or digit;
- the title is at most 300 characters and the sponsor at most 200;
- the phase is one of the defined phases;
- the target enrollment is a whole number from 1 to 1,000,000;
- the site count is a whole number from 0 to 10,000.

**REQ-004 Unique, permanent study IDs.**
A study ID identifies one study for the life of the system.
- IDs are compared without regard to case and are stored in upper case.
- Creating a study with an ID already in use is rejected.
- An ID that belonged to a deleted study cannot be reused, so an audit history never
  mixes two studies.
- A study's ID cannot be changed after creation.

**REQ-005 View studies.**
Any identified user can see the list of studies, showing each study's ID, title, phase,
sponsor and status, and open a study to see all of its fields.

### Changing studies

**REQ-006 Edit a study.**
An identified user can edit a study's title, phase, sponsor, target enrollment and site
count. Fields that were changed are saved, and the rules in REQ-002 and REQ-003 apply.

**REQ-007 Reason for change.**
Every edit, status change and deletion requires a reason for change of 1 to 500
characters, not counting surrounding whitespace. A change without a reason is
rejected and nothing is saved. Creating a study needs no reason: the audit trail
records it as the initial entry.

**REQ-008 Allowed status transitions.**
A status change is accepted only if it appears in this table. Any other change is
rejected, with a message stating which transitions are allowed.

| From | Allowed to |
|---|---|
| Planned | Recruiting, Withdrawn |
| Recruiting | Active not recruiting, Suspended, Terminated |
| Active not recruiting | Completed, Suspended, Terminated |
| Suspended | Recruiting, Active not recruiting, Terminated |
| Completed, Terminated, Withdrawn | none |

The definitions follow ClinicalTrials.gov: *Withdrawn* means stopped before the first
participant enrolled, and *Terminated* means stopped early after enrollment began, so a
Planned study can be withdrawn but not terminated.

**REQ-009 Final statuses are locked.**
Once a study is Completed, Terminated or Withdrawn, its status can never change again.
For example, a Completed study cannot return to Recruiting. Its other fields can still
be corrected under REQ-006 and REQ-007, and those corrections are audited like any
other.

**REQ-010 Identified users only.**
Every change is attributed to an identified user. A request that would change data
without one is rejected and nothing is saved. Viewing also requires an identified user.

### Audit trail

**REQ-011 Audit entry content.**
Every change writes audit entries automatically, with no extra step for the user:
- creating a study writes one entry per field;
- an edit writes one entry per field that actually changed (fields left unchanged
  write nothing);
- a status change writes one entry for the status field;
- a deletion writes one entry for the study as a whole.

Each entry records the study ID, the action (create, update, status change or delete),
the field, the old value, the new value, the reason for change, the username and a
UTC timestamp. The server sets the timestamp; the user's browser does not.

**REQ-012 The audit trail is append-only.**
Audit entries can be added but never modified or deleted. The application offers no
way to edit or remove one, and the database itself rejects any `UPDATE` or `DELETE`
on the audit table, including one issued outside the application.

**REQ-013 Audit history view.**
Each study has a page listing its complete audit history, oldest first, showing every
recorded attribute of every entry. The history of a deleted study remains available.

**REQ-014 A change and its audit entries are saved together.**
A change and its audit entries are written in a single transaction. If the audit
entries can't be written, the change is not saved either, so the data never holds a
change the audit trail doesn't record.

**REQ-015 Deleting a study keeps its history.**
An identified user can delete a study by giving a reason for change. The study no
longer appears in the list, its audit history, including the deletion entry, is kept
and can still be viewed, and its ID cannot be reused (REQ-004).

## Out of scope

These would be required of a real validated system and are deliberately not attempted:

- **Authentication and electronic signatures.** Users identify themselves by choosing a
  username; there are no passwords. Part 11 requires unique credentials and, for
  signed records, electronic signatures (§11.100 to §11.300).
- **Formal validation.** There is no validation plan, risk assessment, or IQ/OQ/PQ
  protocols. The automated tests and traceability matrix show the *shape* of
  requirements-based testing, not a validation package.
- **Concurrent-edit protection.** Two users editing the same study at once is not
  detected; the later save wins, and both changes are audited.
- **Database administration.** Someone with direct access to the database file can drop
  the audit table or replace the file. The append-only rule (REQ-012) guards against
  row-level changes, not against an administrator destroying the database.
