"""ITEM ٣ (تدقيق حي 2026-07-16): زرّ «حلّل السوق» — قرار مُعلَن.

الأدلة (مراجعة شيفرة ساكنة — لا نداء حيّ ممكن من هذه البيئة): /analyze
(api.py) يحجز تفعيلة كلود واحدة لحكم المرحلة ٢ (`policy["with_ai"]`) متى
كان ANTHROPIC_API_KEY مضبوطاً — تكلفة صامتة، والزرّ كان بلا أي تلميح toolt
ip يشرحها، خلافاً لزرّي «معاينة فورية»/«بحث عميق». وفي الوقت نفسه فهو
المسار الوحيد القادر على ترتيب/مقارنة أسواق مرشّحة متعددة (كومتريد+البنك
الدولي) — /research يتطلب سوقاً واحداً مُختاراً سلفاً فلا يقدر على هذا.

القرار: إبقاء الزرّ (قيمة حقيقية غير مكرَّرة) + إعادة تسميته بصدق («مسح
الأسواق ←» بدل «حلّل السوق ←» الغامضة) + تلميح يفصح عن التكلفة المحتملة —
لا حذف، ولا تسمية مضلِّلة بأنه «الأدق».

Run: python3 -m pytest tests/test_item3_analyze_screen_button.py -q
"""
import os

_HTML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "web", "index.html")


def _html() -> str:
    return open(_HTML, encoding="utf-8").read()


def test_run_button_renamed_away_from_ambiguous_label():
    html = _html()
    assert "مسح الأسواق ←" in html
    # لم تعد التسمية الغامضة القديمة حاضرة على الزرّ (id="runBtn" نفسه).
    assert 'id="runBtn"' in html
    btn_start = html.index('id="runBtn"')
    btn_tag_end = html.index("</button>", btn_start)
    btn_html = html[btn_start:btn_tag_end]
    assert "حلّل السوق" not in btn_html


def test_run_button_now_discloses_cost_via_tooltip():
    html = _html()
    btn_start = html.index('id="runBtn"')
    btn_tag_end = html.index("</button>", btn_start)
    btn_html = html[btn_start:btn_tag_end]
    assert "title=" in btn_html
    assert "تفعيلة" in btn_html            # يفصح عن تكلفة كلود الاحتمالية
    assert "بحث عميق" in btn_html          # يوجّه للمسار الموثوق


def test_i18n_dict_mirrors_the_new_label_both_languages():
    html = _html()
    assert 'run:{ar:"مسح الأسواق ←",en:"Screen markets →"}' in html


def test_all_action_buttons_have_honest_tooltips_and_distinct_labels():
    """كل زرّ فعل (بحث عميق/مسح الأسواق) يحمل تلميحاً — لا زرّ لا يمكن لصاحب
    المنصة نفسه أن يشرح غرضه (شرط المستخدم الصريح لهذا البند). زرّ «معاينة
    فورية» (snapBtn) حُذف بالكامل (PART D، قرار مالك نهائي) فلم يعد يُختبَر."""
    html = _html()
    assert 'id="snapBtn"' not in html      # الزرّ محذوف — لا يتيم متبقٍّ
    for btn_id in ("researchBtn", "runBtn"):
        start = html.index(f'id="{btn_id}"')
        end = html.index("</button>", start)
        tag = html[start:end]
        assert "title=" in tag, f"#{btn_id} still has no tooltip"
