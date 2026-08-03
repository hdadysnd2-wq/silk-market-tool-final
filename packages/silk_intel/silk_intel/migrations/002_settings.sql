-- M2A — إعدادات خادمية قابلة للحفظ (مفاتيح المصادر تُدار من الخادم لا من متصفح
-- المستخدم). القيم تُخزَّن كما هي؛ نقاط الـAPI لا تُعيدها أبداً (كتابة/وجود فقط).
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
