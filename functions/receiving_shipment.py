"""Bounded, database-free packing-list / serial-export receiving generation."""
from io import BytesIO
from zipfile import ZipFile, BadZipFile
from collections import Counter, defaultdict, deque
from pathlib import Path
import re
import shutil
from datetime import datetime

import pdfplumber
from openpyxl import Workbook, load_workbook
from functions.quickbooks_receipt import parse_receipt, append_literal
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ALIASES = {
    'M.242-SSD-256GB-PCIe34-TLC5WT-TD1': 'M.242-SSD-256GB-P34-TLC5WT-TD1',
    'M.280-SSD-256GB-PCIe44-TLC5WT-TD2': 'M.280-SSD-256GB-P44-TLC5WT-TD2',
    'M.280-SSD-512GB-PCIe44-TLC5WT-TD2': 'M.280-SSD-512GB-P44-TLC5WT-TD2',
}
SKIP_PREFIXES = ('Cbl', 'DIN', 'AccsyBx', 'Gpubr', 'Ant', 'FK', 'TB', 'Screw', 'Wmkit', 'Dmpbr', 'DtC')
ITEM_RE = re.compile(r'^(?:(?P<carton>\d+(?:-\d+)?)\s+)?(?P<model>.+?)\s+(?P<qty>\d+)\s+(?P<net>\d+\.\d+)(?:\s|$)')
POD_RE = re.compile(r'^Customer PO No\s*\.:\s*(POD-\d+)\s*$', re.I)


def validate_excel(path):
    try:
        with ZipFile(path) as archive:
            if sum(entry.file_size for entry in archive.infolist()) > 100 * 1024 * 1024:
                raise ValueError('Workbook is too large after decompression.')
    except BadZipFile as exc:
        raise ValueError('Upload a valid .xlsx or .xlsm workbook.') from exc


def parse_packing(path):
    items, current, last_carton = [], None, ''
    total_cartons = None
    printed_qty = None
    invoices = set()
    with pdfplumber.open(path) as pdf:
        if len(pdf.pages) > 100:
            raise ValueError('Upload packing PDFs with at most 100 pages.')
        for page_number, page in enumerate(pdf.pages, 1):
            for raw in (page.extract_text() or '').splitlines():
                line = raw.strip()
                inv = re.search(r'INV NO\.:\s*(\d+)', line)
                if inv:
                    invoices.add(inv.group(1))
                total = re.match(r'^TOTAL\s+(\d+)\s+CTNS', line)
                if total:
                    total_cartons = int(total.group(1))
                    if current:
                        items.append(current)
                        current = None
                    continue
                qty_total = re.match(r'^(\d+)\s+[\d.]+\s+[\d.]+\s+KG$', line)
                if qty_total:
                    printed_qty = int(qty_total.group(1))
                    continue
                match = ITEM_RE.match(line)
                if match:
                    if current:
                        items.append(current)
                    carton = match['carton']
                    if carton:
                        last_carton = carton
                    model = match['model'].strip()
                    current = {'page': page_number, 'carton': last_carton,
                               'original': model, 'part': ALIASES.get(model, model),
                               'qty': int(match['qty']), 'pod': '', 'description': []}
                    continue
                pod = POD_RE.match(line)
                if pod:
                    if current is None or current['pod']:
                        raise ValueError(f'Unexpected POD on packing page {page_number}')
                    current['pod'] = pod.group(1).upper()
                elif current and line not in ('Packing List', 'Weight Weight') and not line.startswith('CARTON No'):
                    current['description'].append(line)
        if current:
            items.append(current)
    if total_cartons is None or printed_qty is None or len(invoices) != 1:
        raise ValueError('Missing packing-list invoice or printed totals')
    if sum(item['qty'] for item in items) != printed_qty:
        raise ValueError('Extracted packing quantity does not match printed total')
    if max(int(i['carton'].split('-')[-1]) for i in items) != total_cartons:
        raise ValueError('Packing carton maximum differs from printed carton total')
    if len(items) > 20000 or sum(item['qty'] for item in items) > 20000:
        raise ValueError('Generate at most 20,000 units per shipment.')
    for number, item in enumerate(items, 1):
        item['line'] = number
        item['box'] = f"{total_cartons}--{item['carton']}"
    return items, invoices.pop(), total_cartons, printed_qty


def read_serials(path, invoice):
    validate_excel(path)
    book = load_workbook(path, read_only=True, data_only=True)
    pool, serials, seen = defaultdict(deque), [], set()
    try:
        rows = iter(book.worksheets[0].values)
        headers = [str(v or '').strip() for v in next(rows)]
        required = ['Customer PO No', 'Ordering Model', 'S/N', 'Invoice No']
        if any(headers.count(key) != 1 for key in required):
            raise ValueError('Serial export requires exactly one each: ' + ', '.join(required))
        positions = {key: headers.index(key) for key in required}
        for row_number, values in enumerate(rows, 2):
            if row_number > 20001:
                raise ValueError('Serial export must contain at most 20,000 rows.')
            row = {key: str(values[index] or '').strip() for key, index in positions.items()}
            if not any(row.values()):
                continue
            if row['Invoice No'] != invoice:
                raise ValueError(f'Serial export row {row_number}: invoice mismatch')
            serial = row['S/N']
            if not serial or not row['Customer PO No'] or not row['Ordering Model']:
                raise ValueError(f'Serial export row {row_number}: incomplete allocation key')
            if serial.upper() in seen:
                raise ValueError(f'Duplicate serial in export: {serial}')
            seen.add(serial.upper())
            model = ALIASES.get(row['Ordering Model'], row['Ordering Model'])
            pool[(row['Customer PO No'], model)].append(serial)
            serials.append([row_number, row['Customer PO No'], row['Ordering Model'], serial, row['Invoice No']])
    finally:
        book.close()
    return pool, serials


def read_references(path):
    """Match notebook VLOOKUP semantics: first exact POD match wins."""
    if path is None:
        return {}
    validate_excel(path)
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        rows = iter(book.worksheets[0].values)
        headers = [str(value or '').strip() for value in next(rows, ())]
        if headers.count('POD') != 1 or headers.count('Reference') != 1:
            raise ValueError('Reference workbook requires POD and Reference columns.')
        pod_index, reference_index = headers.index('POD'), headers.index('Reference')
        references = {}
        for number, row in enumerate(rows, 2):
            if number > 100001:
                raise ValueError('Reference workbook exceeds 100,000 rows.')
            pod = str(row[pod_index] or '').strip()
            if pod:
                references.setdefault(pod, str(row[reference_index] or '').strip())
        return references
    finally:
        book.close()


def generate(receipt_path, packing_path, serial_path, output=None, reference_path=None):
    receipt = parse_receipt(receipt_path)
    packing, vendor_invoice, cartons, printed_qty = parse_packing(packing_path)
    # User explicitly selected this receipt/packing/export set. QB references
    # and vendor invoice numbers are different identifiers; preserve both.
    # Serial export invoice must still match the packing invoice exactly.
    pool, serial_rows = read_serials(serial_path, vendor_invoice)
    references = read_references(reference_path)
    book = Workbook()
    receiving = book.active
    receiving.title = 'Receiving Log'
    receiving.append(['Date', 'Inv#', 'Box #', 'POD#', 'Part#', 'SN#', 'Qty', 'Reference'])
    audit = book.create_sheet('Row Audit')
    audit.append(['Receiving Excel Row', 'Packing Line', 'Page', 'POD', 'Part', 'Serial Status', 'Policy'])
    exceptions = [['Type', 'Packing Line', 'Part', 'Details']]
    assigned = 0
    for item in packing:
        if not item['pod']:
            exceptions.append(['Missing POD - excluded', item['line'], item['part'],
                               f"Qty {item['qty']}; carton {item['carton']}. No POD guessed."])
            continue
        if reference_path and not references.get(item['pod']):
            exceptions.append(['Missing Reference', item['line'], item['part'], item['pod']])
        expand = not item['part'].startswith(SKIP_PREFIXES)
        for _ in range(item['qty'] if expand else 1):
            serial = pool[(item['pod'], item['part'])].popleft() if expand and pool[(item['pod'], item['part'])] else ''
            assigned += bool(serial)
            append_literal(receiving, [receipt['date'], receipt['reference'], item['box'], item['pod'],
                                       item['part'], serial, 1 if expand else item['qty'], references.get(item['pod'], '')])
            append_literal(audit, [receiving.max_row, item['line'], item['page'], item['pod'], item['part'],
                                  'Assigned from export' if serial else 'No export serial; blank cell',
                                  'Unit' if expand else 'Bulk accessory (notebook prefix policy)'])
    for (pod, part), remaining in pool.items():
        for serial in remaining:
            exceptions.append(['Unused serial', '', part, f'{pod}: {serial}'])
    overview = book.create_sheet('Read Me', 1)
    summary = [
        ['Field', 'Value'], ['QuickBooks receipt / Inv#', receipt['reference']],
        ['Packing / export vendor invoice', vendor_invoice],
        ['Identifier mapping', f"User-selected shipment set: QB {receipt['reference']} and vendor {vendor_invoice} are distinct references; no numeric normalization."],
        ['Receiving date from QB receipt', receipt['date'].isoformat()],
        ['Packing cartons', cartons], ['Packing lines', len(packing)], ['Printed / extracted packing quantity', printed_qty],
        ['Receiving rows', receiving.max_row - 1],
        ['Receiving quantity', sum(row[6] for row in receiving.iter_rows(min_row=2, values_only=True))],
        ['Serials assigned', assigned], ['Serial export rows', len(serial_rows)],
        ['Excluded packing lines without POD', sum(not i['pod'] for i in packing)],
        ['Policy', 'Notebook accessory prefixes retain bulk quantities; all other items expand into Qty 1 rows. Missing export serials remain blank. The receiving workspace retains them and supports later SN entry and database updates.'],
        ['Cartons', 'Inherited across lines/pages until the next explicit carton. Carton ranges retained, not split into guessed individual cartons.'],
        ['Reference', f'Values from {reference_path.name}; first exact POD match, matching notebook VLOOKUP behavior.' if reference_path else 'Blank: POD-Reference.xlsx not supplied.'],
        ['Source of receiving products', 'Packing models, as in notebook. QB component lines are retained separately, not also received (avoids double counting installed parts).'],
        ['Reconciliation', 'Open PO price/bundle reconciliation NOT performed. No open PO data or invoice unit prices used.'],
        ['Excluded lines', 'All no-POD packing lines remain in Packing Lines and Exceptions for manual resolution.'],
        ['Database', 'No database accessed or modified. Review before importing.'],
        ['Files', f'{receipt_path.name}; {packing_path.name}; {serial_path.name}'],
    ]
    for row in summary:
        append_literal(overview, row)
    sheet = book.create_sheet('Packing Lines')
    sheet.append(['Line', 'Page', 'Box #', 'POD#', 'Original Model', 'Normalized Part', 'Qty', 'Description', 'Status'])
    for item in packing:
        append_literal(sheet, [item['line'], item['page'], item['box'], item['pod'], item['original'], item['part'],
                               item['qty'], '\n'.join(item['description']), 'Included' if item['pod'] else 'EXCLUDED - missing POD'])
    sheet = book.create_sheet('Serial Export')
    sheet.append(['Export Row', 'POD', 'Ordering Model', 'S/N', 'Vendor Invoice'])
    for row in serial_rows:
        append_literal(sheet, row)
    sheet = book.create_sheet('QB Source Lines')
    sheet.append(['Line', 'Page', 'QB Item', 'Part', 'Qty', 'Cost', 'Amount', 'Customer:Job', 'Classification'])
    for row in receipt['lines']:
        append_literal(sheet, [row['line'], row['page'], row['item'], row['part'], row['qty'],
                               float(row['cost']), float(row['amount']), row['customer'], row['kind']])
    sheet = book.create_sheet('Exceptions')
    for row in exceptions:
        append_literal(sheet, row)
    for sheet in book:
        sheet.freeze_panes = 'A2'
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='264478')
        for col in sheet.columns:
            sheet.column_dimensions[get_column_letter(col[0].column)].width = min(70, max(14, max(len(str(c.value or '')) for c in col) + 2))
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(vertical='top', wrap_text=True)
                if hasattr(cell.value, 'isoformat'):
                    cell.number_format = 'yyyy-mm-dd'
    if output is None:
        return book
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        backup = output.with_name(f'{output.stem}.backup_{datetime.now():%Y%m%d_%H%M%S_%f}{output.suffix}')
        shutil.copy2(output, backup)
        print(f'Backup: {backup}')
    book.save(output)
    print(f'Saved: {output}')
    for row in summary[:12]:
        print(f'{row[0]}: {row[1]}')
    print(f'Exceptions: {len(exceptions)-1}')


def incoming_document(workbook_content):
    """Create an incoming-form draft; never assert an inspection passed."""
    from docx import Document
    book = load_workbook(BytesIO(workbook_content), read_only=True, data_only=True)
    try:
        rows = list(book['Receiving Log'].iter_rows(min_row=2, values_only=True))
    finally:
        book.close()
    groups = {}
    for row in rows:
        key = (row[2], row[3], row[4])
        group = groups.setdefault(key, {'qty': 0, 'serials': [], 'invoice': row[1]})
        group['qty'] += row[6]
        if row[5]:
            group['serials'].append(str(row[5]))
    document = Document()
    document.add_heading('Incoming Receiving Form — Draft', 0)
    document.add_paragraph('Vendor: Neousys Technology | Inspection result: Pending')
    document.add_paragraph('Generated from shipment draft, not proof of database import or completed inspection.')
    table = document.add_table(rows=1, cols=7)
    table.style = 'Table Grid'
    for cell, value in zip(table.rows[0].cells, ['Box', 'POD', 'Product Number', 'Qty', 'S/N', 'Inv#', 'IQC Result']):
        cell.text = value
    for (box, pod, part), group in groups.items():
        for cell, value in zip(table.add_row().cells,
                               [box, pod, part, group['qty'], ', '.join(group['serials']), group['invoice'], 'Pending']):
            cell.text = str(value or '')
    output = BytesIO()
    document.save(output)
    output.seek(0)
    return output
