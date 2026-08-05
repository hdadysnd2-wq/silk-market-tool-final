FROM python:3.11-slim

WORKDIR /app

# محرّك تحويل PDF غير القابل للتحرير (§3، اتفاق المالك): LibreOffice headless
# (soffice) + خطّ عربي الشكل (Amiri) — بدونهما يقع GET /analyses/{id}/report.pdf
# في فرع 503 «محرّك التحويل غير متاح» فيصبح زرّ «تصدير التقرير (PDF)» ميتاً حياً.
# راجع docs/DEPLOY_RAILWAY.md §6 (بوابة قبول PDF/RTL) و silk_reports.docx_to_pdf.
# The final client deliverable is a non-editable PDF; LibreOffice + an Arabic
# font must ship on the image or the PDF endpoint 503s live.
# §7 (قرار المالك): العائلة الرسمية IBM Plex Sans Arabic (OFL) — تُنزَّل من
# مستودع google/fonts الرسمي (Regular+Bold+SemiBold). بلا هذا الخطّ يبدّل
# LibreOffice صامتًا فيسقط قبول §7؛ curl -f يُفشِل البناء إن تعذّر التنزيل.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libreoffice-writer fonts-hosny-amiri fontconfig curl ca-certificates \
    && mkdir -p /usr/share/fonts/truetype/ibmplex \
    && for w in Regular Bold SemiBold; do \
         curl -fsSL -o "/usr/share/fonts/truetype/ibmplex/IBMPlexSansArabic-$w.ttf" \
           "https://raw.githubusercontent.com/google/fonts/main/ofl/ibmplexsansarabic/IBMPlexSansArabic-$w.ttf"; \
       done \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

# Non-root runtime (least privilege — HIGH-11). This image bundles LibreOffice
# (soffice), which parses untrusted report text, so confining the process to a
# non-root uid is the key mitigation for that RCE surface. Writable runtime
# paths are /app and the data dir (SILK_DATA_DIR, default /app/data: the SQLite
# stores, cache/, traces/). If SILK_DATA_DIR points at a mounted volume, that
# volume must be writable by uid 10001 (see docs/DEPLOY_RAILWAY.md).
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Railway يمرّر PORT وقت التشغيل؛ محليًا يسقط إلى 8000.
# Railway injects PORT at runtime; falls back to 8000 locally.
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}"]
