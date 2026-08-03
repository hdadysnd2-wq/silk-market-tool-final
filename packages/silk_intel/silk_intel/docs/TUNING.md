# بروتوكول التنقيح — بعثات البحث العميق (الموجة ٦، V5)

> يفترض هذا الدليل مفتاح `ANTHROPIC_API_KEY` حياً وشبكة فعلية — لا يعمل
> شيء هنا في هذه البيئة (بلا مفتاح، بلا وصول لـ Comtrade/WorldBank/GDELT/
> WITS) ولا في CI. راجع `docs/DEEP_RESEARCH_DECISIONS.md` لسبب ذلك ولملخّص
> كل قرار تصميم اتُّخذ أثناء البناء.

## الفكرة

بدل تخمين لماذا بعثة ما (`pricing_scout` مثلاً) تعيد نتائج ضعيفة، شغّلها
**وحدها** ضد سوق حقيقي واقرأ أثرها الكامل — البرومبت المُرسَل حرفياً، كل
نداء أداة بمدخله ومخرجه، ولماذا أُسقط أي بند. لا حرق تشغيلة الاثنتي عشرة
بعثة كاملة لتشخيص واحدة.

## الخطوات

### ١) شغّل الحالة الذهبية (أو بعثة مفردة تجريبياً)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export SEARCH_API_KEY=...          # اختياري — pricing_scout/consumer_culture/channels_importers تحتاجه
export COMTRADE_API_KEY=...        # اختياري — يرفع سقف Comtrade من 4 إلى ~500 نداء/يوم

python3 -c "
from silk_market_resolver import resolve_market
from silk_missions import deep_research

ref, _ = resolve_market('Nigeria')
out = deep_research(ref, product='تمور', hs_code='080410',
                     dry_run=True, only_agent='pricing_scout')
print(out['report'].summary)
"
```

يطبع كل حدث تتبّع (`llm_call`/`tool_call`/`finish`) للطرفية فوراً، ويكتبها
أيضاً إلى `data/traces/dryrun-pricing_scout-NGA.jsonl`.

### ٢) افتح الأثر

```bash
python3 -c "
import json
for ln in open('data/traces/dryrun-pricing_scout-NGA.jsonl', encoding='utf-8'):
    e = json.loads(ln)
    print(e['kind'], '-', e.get('tool') or e.get('stop_reason') or e.get('summary'))
"
```

كل سطر `tool_call` يحمل `input`/`output` الفعليين — إن كانت `output` فارغة
دوماً فالمشكلة في الأداة (مفتاح غائب/شبكة)، لا في البعثة.

### ٣) صنّف الفشل

| العرَض | السبب الأرجح |
|---|---|
| كل `tool_call.output` فارغة | أداة فاشلة — تحقق من المفتاح/الشبكة أولاً (`silk_llm_runtime.TOOLS[key]["fn"]`) |
| `llm_call` قليلة جداً، `finish.summary` يقول "غير محسوم" | تعليمات غامضة — البعثة لا تعرف متى تتوقف؛ وضّح معايير الكفاية في `silk_missions.MISSIONS[key]["instructions"]` |
| البعثات الثلاث (`pricing_scout`/`consumer_culture`/`channels_importers`) تبحث بالإنجليزية رغم سوق عربي/غير إنجليزي | تحقق أن `_SEARCH_IN_MARKET_LANGUAGE` لا تزال ملحقة بتعليماتها في `silk_missions.py` |
| `finish.dropped` مرتفع باستمرار | البعثة تكتب ادّعاءات دون استشهاد صريح بمعرّف dpN — أضِّح في التعليمات: "كل رقم يجب أن يستشهد بمعرّف نقطة بيانات" |
| `elapsed_ms` مرتفع، `tool_calls_used` يبلغ الميزانية دوماً | الميزانية ضيقة — ارفع `SILK_MISSION_TOOL_CALLS` (افتراضي 5) لهذه المهمة تحديداً عبر `budget={"tool_calls": N}` |

### ٤) عدّل وأعد التشغيل

عدّل `silk_missions.MISSIONS["pricing_scout"]["instructions"]`، أعد
تشغيل خطوة (١) فقط لهذه البعثة (لا الاثنتي عشرة).

### ٥) قِس الأثر على الجودة

```bash
python3 -m silk_evals --case nigeria_tea
```

يعيد تشغيل الحالة الذهبية **كاملة** (الاثنتا عشرة بعثة + المحلل + التوليف
+ الكاتب/المراجع)، يحسب الدرجة (`silk_evals.evaluate_report`)، ويقارنها
بآخر نتيجة محفوظة في `evals/scores.json` — انخفاض > 10 نقطة = فشل تراجع
معلن (كود خروج 1)، مفيد قبل أي دمج يمسّ برومبتات `silk_missions.py`/
`silk_market_analyst.py`/`silk_ai_judge.py`.

### ٦) سجّل النتيجة

`evals/scores.json` يُحدَّث تلقائياً بعد كل تشغيلة ناجحة (`silk_evals.main`
يكتبها). التزم الملف مع أي PR يغيّر برومبتاً — لوحة قياس تراكمية للجودة
عبر الزمن.

## لوحة التتبّع في الواجهة

كل نتيجة `/research` تحمل `view["deep_research"]["missions"][key]["trace"]`
— `{status, tool_calls, dropped, gaps}` بلمحة واحدة (بلا فتح ملف JSONL) —
مبنية من `silk_render._mission_trace_summary`. الحقل `view["deep_research"]
["trace_id"]` يشير لملف `data/traces/{trace_id}.jsonl` الكامل لمن يريد
التعمّق.

## جلسات التنقيح الأولى المقترحة

الثلاث المقترحة أصلاً بالتكليف الختامي: **نيجيريا** (سوق أفريقي، لغة
إنجليزية)، **الصين** (سوق آسيوي كبير، لغة مختلفة كلياً)، **مصر** (سوق
عربي، تختبر تعليمات "ابحث بلغة السوق" فعلياً بالعربية). كل جلسة = حالة
ذهبية جديدة في `evals/golden_cases.json` بعد التحقق اليدوي من أرقامها
مقابل Comtrade مباشرة (لا نسخ من نتيجة كلود — تحقّق مستقل).
