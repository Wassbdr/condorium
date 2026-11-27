Extract at most five explicit hard requirements from the brief. Return compact JSON:
[{"quote":"no more than $500","kind":"max","limit":500,"unit":"USD"}].
Use a short verbatim quote. Use max for a ceiling, min for a floor (including required
coverage), or rule for a nonnumeric obligation or restriction. "Permits ... only" and
"must not" are restrictions; "no more than" is a ceiling. For max/min, copy the
numeric bound from the quote, using the same units; for rule use null and "".
Do not infer requirements from goals, methods or rubric advice. Return [] if none.
