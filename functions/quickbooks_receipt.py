"""Parse a QuickBooks Item Receipt PDF into a review-only workbook; no DB access.

Usage: python scripts/parse_quickbooks_receipt.py input.pdf output.xlsx
Requires pdfplumber and openpyxl. Layout supported: Item / Description / Qty /
Cost / Amount / Customer:Job / Class, with a Date / Ref. No. header table.
"""
import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import re

import pdfplumber
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

HEADERS = ['Item', 'Description', 'Qty', 'Cost', 'Amount', 'Customer:Job', 'Class']


def money(value):
    return Decimal(value.replace(',', '').replace('$', '').strip())


def parse_receipt(path):
    lines, dates, references, totals = [], set(), set(), set()
    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        if page_count > 100:
            raise ValueError('Upload QuickBooks PDFs with at most 100 pages.')
        for page_number, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ''
            for total in re.findall(r'Item Receipt Total\s*:\s*\$?([\d,]+\.\d{2})', text):
                totals.add(money(total))
            found_items = False
            for table in page.extract_tables():
                if not table:
                    continue
                if table[0] == ['Date', 'Ref. No.']:
                    dates.add(datetime.strptime(table[1][0], '%m/%d/%Y').date())
                    references.add(table[1][1].strip())
                if table[0] != HEADERS:
                    continue
                found_items = True
                for cells in table[1:]:
                    if not any(cells):
                        continue
                    if len(cells) != 7 or not cells[0] or not cells[2]:
                        raise ValueError(f'Unrecognized item row on page {page_number}: {cells!r}')
                    raw_item, description, qty, cost, amount, customer, item_class = cells
                    # Use the Item column, not the descriptive model: the latter
                    # can differ from the actual QuickBooks accounting part.
                    item = raw_item.replace('\n', '').strip()
                    part = item.split(':', 1)[-1].strip()
                    quantity = money(qty)
                    if not quantity.is_finite() or quantity < 0 or quantity != quantity.to_integral_value():
                        raise ValueError(f'Unsupported quantity on page {page_number}: {qty}')
                    cost, amount = money(cost), money(amount)
                    if not cost.is_finite() or not amount.is_finite():
                        raise ValueError('Non-finite monetary value')
                    kind = ('Non-stock charge' if item.casefold().startswith('forwarding charge')
                            else 'Zero quantity' if quantity == 0 else 'Physical item')
                    if len(lines) >= 20000:
                        raise ValueError('QuickBooks receipt exceeds 20,000 lines.')
                    lines.append({'line': len(lines) + 1, 'page': page_number,
                                  'item': item, 'raw_item': raw_item, 'part': part,
                                  'description': description or '', 'qty': int(quantity),
                                  'cost': cost, 'amount': amount, 'customer': customer or '',
                                  'class': item_class or '', 'kind': kind,
                                  'price_check': 'OK' if abs(quantity * cost - amount) <= Decimal('.01')
                                  else 'REVIEW: quantity x cost differs from amount'})
            if not found_items:
                raise ValueError(f'No recognized item table on page {page_number}; refusing a partial parse.')
    if len(dates) != 1 or len(references) != 1 or len(totals) != 1:
        raise ValueError('Expected one consistent receipt date, reference and printed total.')
    total = sum((line['amount'] for line in lines), Decimal(0))
    printed_total = totals.pop()
    if total != printed_total:
        raise ValueError(f'Extracted amount {total} differs from printed total {printed_total}.')
    return {'date': dates.pop(), 'reference': references.pop(), 'total': total,
            'pages': page_count, 'lines': lines}


def append_literal(sheet, values):
    # Source strings must never become spreadsheet formulas.
    sheet.append(values)
    for cell in sheet[sheet.max_row]:
        if isinstance(cell.value, str):
            cell.data_type = 's'


def write_workbook(receipt, source, output):
    book = Workbook()
    overview = book.active
    overview.title = 'Read Me'
    draft = book.create_sheet('Receiving Draft')
    units = book.create_sheet('Unit Rows Draft')
    source_sheet = book.create_sheet('Source Lines')
    physical = [line for line in receipt['lines'] if line['kind'] == 'Physical item']
    notes = [
        ['Field', 'Value'], ['Source PDF', str(source)],
        ['Receipt date (US MM/DD/YYYY)', receipt['date'].isoformat()],
        ['QuickBooks receipt reference', receipt['reference']],
        ['Printed and extracted total', float(receipt['total'])],
        ['PDF pages', receipt['pages']], ['Extracted lines', len(receipt['lines'])],
        ['Positive-quantity physical lines', len(physical)],
        ['Physical quantity total', sum(line['qty'] for line in physical)],
        ['Status', 'DRAFT ONLY - missing POD, carton and serial confirmation'],
        ['Inv# mapping', 'Inv# uses the QuickBooks receipt Ref. No. exactly as printed.'],
        ['POD warning', 'Memo POD list is truncated and has no per-line links. No POD assignments inferred.'],
        ['Serial warning', 'Blank serial means unknown, NOT confirmed non-serialized. Current website skips blank serials.'],
        ['Receiving Draft', 'One row per positive physical source line, preserving its quantity.'],
        ['Unit Rows Draft', 'All positive physical quantities expanded to Qty 1, preserving repeated units. Provisional: confirm which accessories should remain bulk.'],
        ['Source Lines', 'All lines, including zero quantities and forwarding charge. Full Item and Description retained.'],
        ['Item normalization', 'Wrapped Item text joined and category prefix before colon removed. No guessed model substitutions.'],
        ['Reconciliation', 'No database accessed; open PO reconciliation not yet performed.'],
    ]
    for row in notes:
        append_literal(overview, row)
    headers = ['Date', 'Inv#', 'Box #', 'POD#', 'Part#', 'SN#', 'Qty', 'Reference',
               'QB Receipt Ref', 'Source Line', 'Source Page', 'Unit Within Line', 'Review Status', 'Customer:Job']
    draft.append(headers)
    units.append(headers)
    for line in physical:
        base = [receipt['date'], receipt['reference'], '', '', line['part'], '', line['qty'], '',
                receipt['reference'], line['line'], line['page'], '',
                'Confirm POD, carton, serial policy and Reference', line['customer']]
        append_literal(draft, base)
        for unit in range(1, line['qty'] + 1):
            row = base.copy()
            row[6] = 1
            row[11] = unit
            append_literal(units, row)
    source_sheet.append(['Source Line', 'Page', 'QB Item', 'Part#', 'Description', 'Qty',
                         'Cost', 'Amount', 'Customer:Job', 'Class', 'Classification',
                         'Price Check', 'Original Wrapped Item'])
    for line in receipt['lines']:
        append_literal(source_sheet, [line['line'], line['page'], line['item'], line['part'],
                                     line['description'], line['qty'], float(line['cost']),
                                     float(line['amount']), line['customer'], line['class'],
                                     line['kind'], line['price_check'], line['raw_item']])
    for sheet in book:
        sheet.freeze_panes = 'A2'
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='264478')
        for column in sheet.columns:
            width = min(65, max(14, max(len(str(c.value or '').split('\n')[0]) for c in column) + 2))
            sheet.column_dimensions[get_column_letter(column[0].column)].width = width
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(vertical='top', wrap_text=True)
                if isinstance(cell.value, datetime) or hasattr(cell.value, 'isoformat'):
                    cell.number_format = 'yyyy-mm-dd'
    for row in source_sheet.iter_rows(min_row=2, min_col=7, max_col=8):
        for cell in row:
            cell.number_format = '#,##0.00'
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    book.save(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    receipt = parse_receipt(args.pdf)
    write_workbook(receipt, args.pdf, args.output)
    print(f"Receipt {receipt['reference']} | {receipt['date']} | {len(receipt['lines'])} lines | ${receipt['total']:,.2f}")
    print(f'Saved draft workbook: {args.output}')


if __name__ == '__main__':
    main()
