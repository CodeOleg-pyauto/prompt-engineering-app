"""Small XLSX writer using Python's standard library (SpreadsheetML/OOXML)."""
from pathlib import Path
import re
import os
import uuid
import math
import zipfile
from xml.sax.saxutils import escape

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def text(value):
    return escape(re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]', '', str(value))[:32767])


def col(index):
    out = ''
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def worksheet(rows, widths):
    out = [f'<worksheet xmlns="{NS}"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>']
    for i, width in enumerate(widths, 1):
        out.append(f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>')
    out.append('</cols><sheetData>')
    for r, values in enumerate(rows, 1):
        height = max(30, min(400, max(math.ceil(len(str(v)) / max(1, widths[c] - 2)) for c, v in enumerate(values)) * 15 + 12))
        out.append(f'<row r="{r}" ht="{height}" customHeight="1">')
        for c, value in enumerate(values, 1):
            ref = col(c) + str(r)
            style = 1 if r == 1 else 2
            if type(value) in (int, float):
                out.append(f'<c r="{ref}" s="{style}"><v>{value}</v></c>')
            else:
                out.append(f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{text(value)}</t></is></c>')
        out.append('</row>')
    out.append(f'</sheetData><autoFilter ref="A1:{col(len(widths))}{len(rows)}"/></worksheet>')
    return ''.join(out)


def write_xlsx(path, sheets):
    path = Path(path)
    temp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    types = ['<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
    book = [f'<workbook xmlns="{NS}" xmlns:r="{REL}"><sheets>']
    relationships = ['<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    for i, (name, rows, widths) in enumerate(sheets, 1):
        types.append(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
        book.append(f'<sheet name="{text(name)}" sheetId="{i}" r:id="rId{i}"/>')
        relationships.append(f'<Relationship Id="rId{i}" Type="{REL}/worksheet" Target="worksheets/sheet{i}.xml"/>')
    types.append('</Types>'); book.append('</sheets></workbook>')
    relationships.append(f'<Relationship Id="styles" Type="{REL}/styles" Target="styles.xml"/></Relationships>')
    styles = f'''<styleSheet xmlns="{NS}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF0045FF"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'''
    try:
        with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED) as z:
            def put(name, xml):
                z.writestr(name, '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + xml)
            put('[Content_Types].xml', ''.join(types))
            put('_rels/.rels', f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
            put('xl/workbook.xml', ''.join(book))
            put('xl/_rels/workbook.xml.rels', ''.join(relationships))
            put('xl/styles.xml', styles)
            for i, (_, rows, widths) in enumerate(sheets, 1):
                put(f'xl/worksheets/sheet{i}.xml', worksheet(rows, widths))
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
