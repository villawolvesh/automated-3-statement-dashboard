# Lecciones aprendidas — Automated 3-Statement Dashboard

Documento reusable para proyectos de datos/finanzas. Conciso a propósito.

---

## 🥇 Regla de oro: AUDITAR antes de construir

**Siempre hacer un diagnóstico/auditoría ANTES de construir o cambiar algo, y reportarlo
para aprobación. Nunca construir a ciegas.**

Evidencia de este proyecto:
- **Cada cambio precedido de auditoría salió limpio** (entorno, cierre de huecos XBRL,
  conciliaciones de efectivo, derivación de trimestres). Se entendió la fuente primero,
  se validó contra dato público, y el fix fue al primer intento.
- **Cada construcción sin auditoría previa dejó un bug** que hubo que cazar después:
  controles conectados a medias, Q4 ausente, huecos en el Hito 1.

Corolario: el tiempo de auditoría se paga solo. Una hora de diagnóstico evita medio día
de debugging y, peor, de mostrar números equivocados.

---

## 🐞 Tabla de errores de este proyecto

| Síntoma | Causa raíz | Cómo se detectó | Fix | Regla para no repetirlo |
|---|---|---|---|---|
| El selector **"Compare to" estaba muerto** en todos los tabs menos Variance | Los controles se cablearon "a medias": solo `drawVariance` leía `getCompare()`; `drawBalance` no leía ningún control | El usuario probó cambiar el control y no pasó nada; auditoría del código confirmó a qué estaba atado cada control | Rediseño: cada tab de estado quedó comparativo / luego patrón spreadsheet con toggles propios | **Antes de prometer que "todo compara/reacciona", auditar a qué está atado CADA control.** No asumir; rastrear en el código. |
| **Q4 ausente** en modo Quarterly (tablas y gráficas), con un "salto" de períodos | Apple **no reporta el Q4 standalone**: va dentro del 10-K anual. El pipeline solo leía Q1/Q2/Q3 de los 10-Q y omitía el Q4 | Auditoría con datos reales: para FY2024 había Q1/Q2/Q3 pero ningún fact standalone de Q4 (el último fue FY2020) | Derivar el Q4 (income: `FY−(Q1+Q2+Q3)`; cash flow: `FY−9m`) y marcarlo como derivado | **Entender CÓMO reporta la fuente ANTES de modelar períodos.** Trimestral ≠ "4 facts iguales"; cada estado y cada emisor reportan distinto. |
| **Q4 derivado salió NEGATIVO** (−$22B) al primer intento | Se alineó el valor anual por el campo `fiscal_year` de EDGAR, que es **poco fiable**: en un 10-K los 3 años comparativos comparten el mismo `fy` | La suma de trimestres no cuadraba con el anual; el Q4 daba negativo | Alinear el anual por el **año del `period_end`**, no por `fiscal_year` | **En XBRL/EDGAR, alinear por `period_end`, no por el tag `fiscal_year`.** Los comparativos contaminan el tag del filing. |
| **Huecos en el Hito 1**: Total Assets FY2025 y Total Equity FY2024-25 salían vacíos | El mismo concepto económico usa **tags XBRL distintos entre años/empresas** (ej. `StockholdersEquity` vs variantes), y el dedup "más reciente" se quedaba con un 10-Q que el filtro de 10-K descartaba | Validación contra dato público (Apple FY2025 assets ~$359.24B): la celda estaba vacía | `concept_map` con **fallbacks** por prioridad + filtrar a 10-K/FY ANTES del dedup | **Mapear conceptos con fallbacks**; nunca asumir que un tag XBRL es estable entre períodos. Validar cada línea contra dato público. |

---

## 📐 Reglas refinadas

**(a) Derivar con fórmula contable exacta SÍ; estimar/rellenar NO.**
`Q4 = AñoCompleto − 9meses` o `Q_n = YTD_n − YTD_{n−1}` son aritmética exacta sobre cifras
reportadas → válido. Inventar un número, interpolar o "rellenar" un hueco con un supuesto
→ prohibido.

**(b) Marcar TODO lo derivado.** Si una celda no es un dato reportado directo, debe llevar
un indicador + tooltip ("standalone quarter derived from year-to-date filings"). El usuario
debe poder distinguir reportado vs calculado de un vistazo.

**(c) Validar cada cifra contra dato público.** Antes de mostrar, contrastar números clave
contra el 10-K/press release oficial (ej. revenue, net income, márgenes). Si no coincide,
parar y diagnosticar; no publicar.

**(d) Integrity checks que TRUENEN con números malos.** Tests automáticos que fallan (exit
≠ 0) y detienen la publicación si algo no cuadra: balance (A=L+E), efectivo
(inicial+flujos=final), net income (IS=CF), y trimestres (Q1+Q2+Q3+Q4 = anual). Un test que
siempre sale verde no sirve; hay que probar que se pone rojo metiendo un valor malo a propósito.

**(e) Causa ≠ magnitud.** La capa automática solo describe la magnitud de una varianza
("X fue 7.6% de revenue, muy por encima de su promedio de ~4.6%"). El **"por qué"** solo
viene de un archivo curado, verificado a mano y con fuente. Nunca inferir causas en código.

---

## ⏱️ A) Por qué tardó y cómo comprimirlo la próxima

**Causa real:** los requisitos de *comportamiento* se descubrieron **probando**, no se
especificaron al inicio. La mayoría del rework fue de **diseño de producto** (controles,
períodos, comparaciones, notas), **no de datos**. Los datos se blindaron temprano (EDGAR →
SQL → integrity guard, validados contra dato público) y **aguantaron todo el proyecto sin
romperse**. Cada iteración larga fue redibujar UI/UX, no recalcular cifras.

**Patrón observado:** "agrega comparación" → resultó que solo medio control comparaba →
rediseño; "muestra trimestral" → faltaba el Q4 → rediseño; "selector de año" → cortaba
FY2021 → rediseño. Todo era comportamiento no acordado de antemano.

**Regla:** **antes de construir UI, escribir una mini-spec de comportamiento y aprobarla**
(ver plantilla B). 30 minutos de spec acordada habrían evitado ~4 ciclos de rework. El
blindaje temprano de datos fue correcto y hay que repetirlo; el error fue construir UI sin
spec.

---

## 🧩 B) Mini-spec reutilizable para dashboards financieros

Plantilla para acordar ANTES de construir. Llénala y apruébala con el cliente primero.

**Períodos**
- [ ] **Annual** y **Quarterly** definidos.
- [ ] Q4 derivado = `FY − 9M` (= `FY − (Q1+Q2+Q3)`); cash flow standalone desde YTD
      (`Q2=H1−Q1`, `Q3=9M−H1`, `Q4=FY−9M`).
- [ ] Años fiscales **parciales** (en curso) marcados "partial / YTD" y **nunca usados como
      base de comparación anual completa**.
- [ ] El spine cubre **años completos dentro de la ventana** (no cortar a la mitad).

**Vistas estándar** (cada una con subtítulo de "contra qué compara")
- [ ] **Values** ($) · **Growth YoY** (vs mismo período del año pasado) · **Growth QoQ**
      (vs período inmediatamente anterior) · **% of base** (revenue o assets).

**Comparaciones**
- [ ] **Nunca** calcular growth/variance contra un período incompleto o sin base → **n/a**
      (no un % engañoso).

**Gráficas y notas**
- [ ] Gráficas de **un período** → selector propio + título con el período elegido.
- [ ] Gráficas **multi-año** → etiquetadas claramente "5-year".
- [ ] Notas **atadas a su período** (las anuales no aparecen en Quarterly; cada nota solo si
      su período está en vista).
- [ ] Todo lo **derivado** se marca con indicador + tooltip.

**Datos (no negociable)**
- [ ] Fuente oficial (ej. SEC EDGAR), cálculo en **SQL visible y auditable**.
- [ ] **Integrity guard que truene** (exit ≠ 0) y detenga la publicación.
- [ ] Cada cifra clave **validada contra dato público**.

---

## 🐞 C) Errores nuevos de esta fase

| Síntoma | Causa raíz | Cómo se detectó | Regla para no repetirlo |
|---|---|---|---|
| **FY2021 mostraba solo Q3/Q4** en Quarterly (faltaban Q1/Q2) | El spine tenía `LIMIT 20`: contando hacia atrás desde el trimestre más reciente, caía a la mitad de FY2021 y lo rebanaba | El usuario lo vio en el dashboard; auditoría confirmó `LIMIT 20` y que Q1/Q2 FY2021 SÍ existían en los datos | **No capar el spine por conteo fijo.** Cubrir **años fiscales completos dentro de la ventana** (`fiscal_year ≥ mínimo del anual`). Nunca cortar un año a la mitad. |
| **Una auditoría "verde" no cachó el bug de FY2021** | La auditoría iteró los períodos **desde el spine** (ya capado), así que FY2021 tenía <4 trimestres y el check **se saltó** en silencio | Solo al pedir cobertura explícita de FY2021 salió la falla | **Las auditorías deben cubrir TODOS los períodos explícitamente** (rango fijo FY2021–FYn, no "lo que haya en el spine"). Un check que se auto-excluye no es un check. Listar cobertura (N celdas, qué años) en el reporte. |
