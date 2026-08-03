# FINAL STATUS — أمر العمل الرئيس (§1–§8) · master-prompt close-out

> **التاريخ:** 2026-07-19 · **الفرع:** `claude/wave3-audit-high` (Wave 3) فوق
> `main @ 95c1bee`. كل ادعاء «تمّ» مرساةٌ إلى `file:line` واسمِ اختبار — لا
> ادّعاء بلا دليل (LAW §2، ثلاثيّة الدلاء).
>
> **صنف الدليل الإجماليّ:** رُتبة ١ هرمتيّة خضراء (`pytest tests/ -q` →
> **1300 passed, 17 skipped**). رُتبتا ٢–٣ (خادم/متصفّح حقيقيّ + قبول PDF)
> تُشغَّلان في وظيفة `e2e-live-shape` بالخطّ مثبَّتًا — لا تُدّعى خضراء هنا قبل
> أن يخضرّ CI على الفرع.

## الجدول الجامع · §1–§8

| § | البند | الحالة | المرساة (file:line) | الاختبارات |
|---|---|---|---|---|
| **§1** | العملة بالدولار حصراً (لا تحويل ريالي، لا «م$») | 🟢 DONE | `silk_render._apply_merchant_language`؛ بوابة الأسلوب `silk_quality_gate.py:_MSHORT_STYLE_RE` | `test_render_strips_any_sar_conversion_parenthetical`، `test_style_gate_fails_on_currency_shorthand_and_inline_enumeration` |
| **§2** | سرّية المُسلَّم + **جهة الكتابة** | 🟢 DONE (هذه الموجة) | بوابة: `silk_quality_gate.py:159-162` (`research_track_leak`/`facts_list_leak`)؛ مُنقّيات `silk_render.py:616,793` + `silk_reports.py:1560-1602,1686`؛ **توجيه الكاتب** `silk_ai_judge.deep_report` + نزع التحفيز «بين الحقائق»→«ضمن الحقائق» | `test_wave3_writer_confidentiality.py` (2)، `test_quality_gate_fails_on_confidentiality_leak_tokens`، `test_client_sanitizer_covers_guard` |
| **§3** | تشكيل عربيّ (RTL shaping، لا مربّعات/شقّ) | 🟢 DONE | `silk_reports._shape_safe_ar` + `_pdf_diacritic_free_copy` (تجريد الحركات على مستوى zip لكلّ جزء XML) | `test_docx_brand_is_shape_safe_no_combining_marks`، `test_strip_set_is_only_combining_marks_never_base_letters`، `test_shape_safe_helper_strips_only_combining_marks` |
| **§4** | هندسة RTL (jc=start، لا انقلاب) | 🟢 DONE | `silk_reports._set_rtl_paragraph` (`w:bidi`+`jc=start`)، `_set_table_rtl` (`bidiVisual`)؛ مقياسٌ مُعايَر `tools/rtl_calibration.py` (إمضاء الانقلاب = تثبيتٌ يساريّ، مراجع مطلقة) | `test_pdf_rtl_geometry_and_arabic_font` (SILK_PDF_ACCEPTANCE)، `test_rtl_measurer_calibration_ab`، `test_docx_is_rtl_document_wide` |
| **§5** | الاكتمال (لا بتر، لا «…» ذيليّة) | 🟢 DONE | استمرارٌ-ثمّ-فشل `silk_ai_judge.py:1028-1064` + `_continue_truncated_report:1081` + `_writer_incomplete:1067`؛ بوابةُ «…» `silk_quality_gate.py:93-106` (حرس FAIL) | `test_quality_gate_fails_on_trailing_ellipsis`، `test_writer_escalation_meters_every_attempt_in_cost`، `test_truncated_then_continuation_completes_ships_full_report`، `test_writer_continuation_call_uses_the_ceiling_not_the_base_budget` |
| **§6** | سجل الأدلة للمدققين (اسم+رابط+تاريخ من طبقة البيانات) | 🟢 DONE (هذه الموجة) | سجلّ روابط عموميّ `silk_data_layer.SOURCE_PUBLIC_URL` + `public_source_url`؛ `silk_reports._evidence_url` (محدّد→سجلّ→«—»، لا اختلاق)؛ عمود «الرابط» في ملحق العميل `silk_reports.py:_client_evidence_appendix` | `test_wave3_evidence_urls.py` (8)، `test_finding_assembly_uses_public_source_not_tool_use`، `test_evidence_log_uses_public_source_badge_no_raw_confidence` |
| **§7** | ترقية طباعة تقارير العميل (خطّ/مقاسات/جداول) | 🟢 DONE (هذه الموجة) | `silk_reports._RTL_BODY_FONT="IBM Plex Sans Arabic"` + `_TYPO` + `_apply_typography`؛ جداول `_add_table`/`_set_table_borders`/`_set_cell_margins` (رأس #166534، شريط #F2F7F3، حدود #BBBBBB)؛ فحص الخطّ `has_plex_arabic_font` | `test_wave3_typography.py` (6، منها `test_pdffonts_embeds_plex_regular_and_bold` تحت SILK_PDF_ACCEPTANCE) |
| **§8** | صوتٌ أكاديميّ (موجّه + مراجعة + بوابة أسلوب حتمية) | 🟢 DONE (هذه الموجة) | موجّه `silk_style_contract.py:49-60` + `silk_ai_judge.py:838-856`؛ تمريرةٌ لغوية `silk_ai_judge.py:1164-1171`؛ بوابةٌ مُدرَّجة `silk_quality_gate._check_style` (ثقة سياقيّة FAIL؛ روابط/أرقام ٣–٤ WARN، ≥٥ FAIL) + `style_digest` (يُطبَع دائمًا) | `test_wave3_style_gate_tiers.py` (10)، `test_style_gate_*`، `test_writer_prompt_carries_style_contract_additions`، `test_reviewer_prompt_has_language_pass` |

## مسار التسليم عبر الموجات · shipping ledger

- **Wave 1** (#123): استخبارات ما-قبل-التشغيل — مصنّف HS + بوّابة hs6 + تنبيه دولة المنشأ.
- **Wave 1.5** (#124): كنسُ التعميم — العائلات A/C/D.
- **Wave 2** (#125): عنقود أوّل-PDF-حيّ — نظافة جدول القيادات + تشكيل العلامة + A4 + قوالب مُعمَّمة + الطيّتان B/E؛ ثمّ معايرةُ مقياس §4 (إمضاء الانقلاب = تثبيتٌ يساريّ).
- **Wave 3** (#126، هذه): §6 روابط أدلة حقيقية + §2 سرّية الكاتب + §8 تدرّج بوابة الأسلوب + §7 ترقية الطباعة. §5 مؤكَّدٌ منجَزًا سابقًا (لا شيفرة).

## عقودٌ لم تُمَسّ · invariants preserved

عقد عدم الاختلاق (`DataPoint(None, conf 0.0)` عند الفشل) سارٍ في كل مسار جديد:
سجلّ §6 يعيد «—» لا رابطًا مخترَعًا؛ نمط ثقة §8 سياقيّ لا صيدَ كسورٍ مجرّدة؛
`jc=start` (لا right) ثابت. رُتبة ١ خضراء بالكامل بعد كل موجة.

## ما يبقى بيد المالك · owner-gated

- **دمج #126** (سلطة المالك الوحيدة، LAW §1) بعد خضرة `e2e-live-shape` على الفرع
  (قبول §7: `pdffonts` يُظهِر IBMPlexSansArabic Regular+Bold مُضمَّنَين؛ §4 أخضر).
- لا نشرٌ ولا إنفاقٌ مدفوعٌ بلا موافقةٍ صريحة.
