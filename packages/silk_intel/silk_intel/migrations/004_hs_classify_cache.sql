-- الموجة ٣ (المصنّف العام) — ذاكرة تصنيف HS لكل اسم منتج مطبَّع، كي لا
-- يُعاد نداء كلود لنفس المنتج مرارًا (بلاغ المالك: "فراشات مكلفة" — نداءٌ
-- واحدٌ لكل منتج جديد فقط، صفرٌ لتكرار). القيمة JSON خام (شكل الاقتراح
-- الكامل بمرشّحيه) — لا يمسّ جدول settings (سياجٌ أمنيٌّ منفصل للمفاتيح).
CREATE TABLE IF NOT EXISTS hs_classify_cache (
    product_key TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
