-- ── audit_log غير قابل للتعديل · append-only enforcement (M-5) ────────────────
-- سجلّ التدقيق هو الدليل على خروقات العزل بين المستأجرين (رفض القراءة، تمويل
-- المشرف، تغيير الطبقة، الدخول). كان قابلاً للتعديل والحذف بحرّية بينما دفتر
-- الأستاذ وسجلّ الموافقة محميّان بمشغّلات RAISE(ABORT). هذا الترحيل يمنح
-- audit_log نفس ضمان عدم العبث: لا UPDATE ولا DELETE.
--
-- The audit log is the record used to prove tenant-isolation breaches. It was
-- freely UPDATE/DELETE-able while ledger_entries and consent_registry were
-- trigger-protected. audit.record only ever INSERTs, so blocking mutation is a
-- pure hardening with no behavioral impact on the app.
CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_update
    BEFORE UPDATE ON audit_log
    BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_delete
    BEFORE DELETE ON audit_log
    BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
