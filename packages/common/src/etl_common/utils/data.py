_NUMERIC_KEYWORDS = (
    "cantidad",
    "qty",
    "monto",
    "amount",
    "precio",
    "price",
    "bruto",
    "neto",
    "impuesto",
    "tax",
    "descuento",
    "discount",
    "total",
)


def clean_and_format_row(row: list[object], headers: list[str]) -> list[object]:
    """Normalize a data row: strip leading quotes and coerce numeric columns."""
    cleaned_row: list[object] = []

    for i, value in enumerate(row):
        if i >= len(headers):
            cleaned_row.append(value)
            continue

        header = headers[i]

        if isinstance(value, str) and value.startswith("'"):
            value = value[1:]

        if any(kw in header.lower() for kw in _NUMERIC_KEYWORDS):
            try:
                if value and str(value).strip():
                    num_value = float(str(value))
                    value = (
                        int(num_value)
                        if num_value == int(num_value)
                        else round(num_value, 2)
                    )
            except (ValueError, TypeError):
                pass

        cleaned_row.append(value)

    return cleaned_row
