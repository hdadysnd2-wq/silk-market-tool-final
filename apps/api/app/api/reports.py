"""Product export-intelligence report: JSON for the app, HTML for download.

The HTML endpoint renders a self-contained document (all CSS inline) so a factory
can save, print, or forward it with no dependency on the running app.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.background import BackgroundTask

from app.api.deps import DbDep, get_owned_product
from app.models import Product
from app.schemas.report import ProductReportOut
from app.services.report import build_product_report
from app.services.report_view import build_engine_result, build_executive_result

_DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

router = APIRouter(tags=["reports"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

_SUPPORTED_LOCALES = {"en", "ar"}

# Template labels, kept here (not in the frontend next-intl catalog) because the
# HTML document is rendered entirely server-side.
_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "platform": "Silk Export Intelligence",
        "report_title": "Export Intelligence Report",
        "generated": "Generated",
        "overview": "Overview",
        "markets": "Markets",
        "buyers": "Buyers",
        "contacts": "Contacts",
        "import_value": "Import value (latest year)",
        "product_hs": "Product & Classification",
        "hs_code": "HS code",
        "hs_description": "Classification",
        "description": "Description",
        "price": "Target price",
        "confirmed": "Confirmed",
        "suggested": "Suggested",
        "not_classified": "Not classified yet",
        "competitor": "Competing exporter",
        "value": "Value (USD)",
        "share": "Share",
        "top_buyers": "Top ranked buyers",
        "legal_review": "Legal review",
        "employees": "employees",
        "world_funnel": "World market funnel",
        "shortlisted": "Shortlisted markets",
        "market": "Market",
        "data_year": "Data year",
        "transit_hub": "transit hub",
        "mirror": "mirror data",
        "no_snapshot": "No competitor snapshot has been generated for this market yet.",
        "no_markets": "No markets have been analyzed for this product yet.",
        "disclaimer": (
            "Buyer and market data is compiled from customs records, trade "
            "statistics, and business directories. Verify before outreach."
        ),
    },
    "ar": {
        "platform": "سِلك لذكاء التصدير",
        "report_title": "تقرير ذكاء التصدير",
        "generated": "تم الإنشاء",
        "overview": "نظرة عامة",
        "markets": "الأسواق",
        "buyers": "المشترون",
        "contacts": "جهات الاتصال",
        "import_value": "قيمة الاستيراد (آخر سنة)",
        "product_hs": "المنتج والتصنيف",
        "hs_code": "الرمز الجمركي",
        "hs_description": "التصنيف",
        "description": "الوصف",
        "price": "السعر المستهدف",
        "confirmed": "مؤكد",
        "suggested": "مقترح",
        "not_classified": "لم يُصنَّف بعد",
        "competitor": "مُصدِّر منافس",
        "value": "القيمة (دولار)",
        "share": "الحصة",
        "top_buyers": "أعلى المشترين ترتيبًا",
        "legal_review": "مراجعة قانونية",
        "employees": "موظف",
        "world_funnel": "قمع الأسواق العالمية",
        "shortlisted": "الأسواق المرشحة",
        "market": "السوق",
        "data_year": "سنة البيانات",
        "transit_hub": "ميناء عبور",
        "mirror": "بيانات معكوسة",
        "no_snapshot": "لم يتم إنشاء لقطة للمنافسين في هذا السوق بعد.",
        "no_markets": "لم يتم تحليل أي أسواق لهذا المنتج بعد.",
        "disclaimer": (
            "بيانات المشترين والأسواق مُجمَّعة من سجلات الجمارك وإحصاءات التجارة "
            "وأدلة الأعمال. يُرجى التحقق قبل التواصل."
        ),
    },
}


def _usd(value: float | int | None) -> str:
    """Compact USD formatting: $1.2M, $340K, $1,234, or an em dash when empty."""
    if value is None:
        return "—"
    value = float(value)
    sign = "-" if value < 0 else ""
    n = abs(value)
    if n >= 1_000_000_000:
        return f"{sign}${n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{sign}${n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{sign}${n / 1_000:.0f}K"
    return f"{sign}${n:,.0f}"


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["usd"] = _usd
    return env


_ENV = _environment()


def _normalize_locale(locale: str) -> str:
    return locale if locale in _SUPPORTED_LOCALES else "en"


@router.get("/products/{product_id}/report", response_model=ProductReportOut)
def product_report(
    db: DbDep,
    product: Product = Depends(get_owned_product),
    locale: str = Query("en"),
) -> ProductReportOut:
    return build_product_report(db, product, _normalize_locale(locale))


@router.get("/products/{product_id}/report.html", response_class=HTMLResponse)
def product_report_html(
    db: DbDep,
    product: Product = Depends(get_owned_product),
    locale: str = Query("en"),
) -> HTMLResponse:
    loc = _normalize_locale(locale)
    report = build_product_report(db, product, loc)
    is_ar = loc == "ar"

    html = _ENV.get_template("report.html").render(
        r=report,
        locale=loc,
        t=_LABELS[loc],
        product=report.product,
        factory=report.factory,
        product_name=report.product.name_ar if is_ar else report.product.name_en,
        factory_name=report.factory.name_ar if is_ar else report.factory.name_en,
        product_description=(
            report.product.description_ar if is_ar else report.product.description_en
        ),
        hs_description=(
            report.product.hs_description_ar if is_ar else report.product.hs_description_en
        ),
    )
    return HTMLResponse(content=html)


@router.get("/products/{product_id}/report.docx")
def product_report_docx(
    db: DbDep,
    product: Product = Depends(get_owned_product),
) -> FileResponse:
    """The full report as a Word document (decision #7 — on demand).

    Derived from the engine's ONE template: platform data → ``build_engine_result``
    → ``silk_render.build_view`` → ``silk_reports.render_docx``. Every figure keeps
    its source line and the "limits of this report" section is never dropped; a
    value the platform cannot source is shown as a declared gap, never fabricated
    (I1). Returns 501 if python-docx is unavailable, mirroring the engine.
    """
    from silk_render import build_view
    from silk_reports import render_docx

    result = build_engine_result(db, product)
    view = build_view(result)

    tmp_dir = tempfile.mkdtemp(prefix="silk_report_")
    try:
        path = render_docx(view, str(Path(tmp_dir) / "report.docx"))
    except RuntimeError as exc:  # python-docx missing → the engine raises this
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=501, detail="Word export is unavailable") from exc
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    filename = f"silk_report_{product.id}.docx"
    return FileResponse(
        path,
        media_type=_DOCX_MEDIA_TYPE,
        filename=filename,
        background=BackgroundTask(shutil.rmtree, tmp_dir, ignore_errors=True),
    )


@router.get("/products/{product_id}/report/executive")
def product_report_executive(
    db: DbDep,
    product: Product = Depends(get_owned_product),
) -> FileResponse:
    """The Executive Multi-Market Report as a Word document, rendered inline.

    Same seam as the full docx export (decision #7): platform data →
    ``build_executive_result`` → ``silk_render.build_view`` →
    ``silk_reports.render_executive_docx``. A product with zero analyses still
    returns 200 — the engine renders a declared-gap report (I1), never a
    fabricated one. Returns 501 if the Word renderer is unavailable, mirroring
    the full export.
    """
    from silk_render import build_view

    try:
        from silk_reports import render_executive_docx
    except ImportError as exc:  # engine build without the executive renderer
        raise HTTPException(status_code=501, detail="Word export is unavailable") from exc

    result = build_executive_result(db, product)
    view = build_view(result)

    tmp_dir = tempfile.mkdtemp(prefix="silk_exec_report_")
    try:
        path = render_executive_docx(view, str(Path(tmp_dir) / "executive.docx"))
    except RuntimeError as exc:  # python-docx missing → the engine raises this
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=501, detail="Word export is unavailable") from exc
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    filename = f"executive_{product.id}.docx"
    return FileResponse(
        path,
        media_type=_DOCX_MEDIA_TYPE,
        filename=filename,
        background=BackgroundTask(shutil.rmtree, tmp_dir, ignore_errors=True),
    )
