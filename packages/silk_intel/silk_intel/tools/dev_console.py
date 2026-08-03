"""أداة مطوّر (M0): نُقلت من app.py — ليست واجهة المنتج (الواجهة web/index.html).

واجهة سِلك — Streamlit UI over silk_engine.

How to run / طريقة التشغيل:
    streamlit run app.py

Streamlit is an OPTIONAL dependency. The core stays import-safe without it:
`python3 -c "import app"` succeeds even when streamlit is not installed — the
guarded main() prints a hint instead of crashing.

Founding principle stays visible in the UI: every number carries its SOURCE and
confidence; empty/None means "no data" (NOT zero demand); all results are
PRELIMINARY.
"""
from __future__ import annotations

import logging

import silk_engine
from silk_market_ranker import WEIGHTS

log = logging.getLogger(__name__)


def _markets_table(markets: list[dict]) -> list[dict]:
    """جدول الأسواق المختصر — rows derived from the ONE view template (§10.1)."""
    from silk_render import build_view
    view = build_view({"markets": markets, "classified": True})
    return [{
        "السوق / Country": m["country"],
        "الدرجة / Score": round(m.get("score") or 0.0, 3),
        "الثقة / Confidence": m.get("confidence", 0.0),
        "مكوّنات / Components": m["components_present"],
    } for m in view["markets"]]


def _render_market(st, row: dict) -> None:
    """تفصيل سوق واحد — per-market provenance breakdown + jury verdict."""
    present = sum(1 for dp in row["components"].values() if dp.value is not None)
    title = (f"{row['country']} — score={row.get('total_score', 0.0):.3f} | "
             f"conf={row.get('confidence', 0.0)} | {present}/{len(WEIGHTS)} comps")
    with st.expander(title):
        st.caption(row.get("recommendation", ""))
        # كل مكوّن: القيمة + المصدر + الثقة — value + SOURCE + confidence per comp.
        comp_rows = []
        for name, dp in row["components"].items():
            comp_rows.append({
                "المكوّن / Component": name,
                "القيمة / Value": "—  (لا بيانات / no data)" if dp.value is None
                                  else dp.value,
                "المصدر / Source": getattr(dp, "source", "") or "—",
                "الثقة / Confidence": getattr(dp, "confidence", 0.0),
                "ملاحظة / Note": getattr(dp, "note", "") or "",
            })
        st.table(comp_rows)

        jury = row.get("jury")
        if jury:
            st.markdown("**حكم اللجنة / Jury verdict**")
            st.write(jury.get("verdict", ""))
            st.caption(
                f"confidence={jury.get('confidence', 0.0)} · "
                f"agents_with_data={jury.get('agents_with_data', 0)}/"
                f"{jury.get('agents_total', 0)} · "
                f"data_gaps={jury.get('data_gaps', [])}"
            )


def render(st, product: str, year: int | None) -> None:
    """نفّذ التحليل واعرضه — run analyze() and render the whole result."""
    with st.spinner("جارٍ التحليل… / analyzing (real public data)…"):
        result = silk_engine.analyze(product, year=year)

    st.subheader(f"المنتج / Product: {result['product']}")
    if not result.get("classified"):
        st.error("تعذّر تصنيف المنتج إلى رمز HS — could not classify product "
                 "(no HS code guessed).")
        st.caption(result.get("hs_note", ""))
        return

    st.markdown(
        f"**رمز HS / HS code:** `{result['hs_code']}` "
        f"(conf={result['hs_confidence']}) · **السنة / Year:** {result['year']}"
    )
    st.caption(result.get("hs_note", ""))

    markets = result.get("markets", [])
    if markets:
        st.markdown("### الأسواق مرتّبة (الأفضل أولاً) — markets ranked best-first")
        st.table(_markets_table(markets))
        st.markdown("#### التفصيل لكل سوق (المصدر + الثقة) — per-market breakdown")
        for row in markets:
            _render_market(st, row)
    else:
        st.warning("لا أسواق لعرضها — no markets to show.")

    st.info(result.get("note", ""))


def main() -> None:
    """نقطة الدخول — lazy Streamlit entry point (guarded import)."""
    try:
        import streamlit as st
    except ImportError:
        print("streamlit is not installed. Run:  pip install streamlit\n"
              "Then launch the UI with:  streamlit run app.py")
        return

    st.set_page_config(page_title="سِلك / Silk Market Intelligence", page_icon="🧵")
    st.title("🧵 سِلك لذكاء الأسواق — Silk Market Intelligence")
    st.warning(
        "النتائج **مبدئية (PRELIMINARY)** ومبنية على بيانات عامة حقيقية فقط. "
        "القيم الفارغة/None تعني **لا بيانات** (وليس طلبًا صفريًا). "
        "Results are PRELIMINARY; empty/None means NO DATA, not zero demand."
    )

    product = st.text_input("اسم المنتج / Product name (AR/EN)", value="")
    year_in = st.text_input("السنة (اختياري) / Year (optional)", value="")

    if st.button("حلّل / Analyze"):
        if not product.strip():
            st.error("أدخل اسم منتج / please enter a product name.")
            return
        year: int | None = None
        if year_in.strip():
            try:
                year = int(year_in.strip())
            except ValueError:
                st.error("السنة غير صالحة / invalid year — using default.")
        render(st, product.strip(), year)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
