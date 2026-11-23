"""
Generador del Acuerdo de Confidencialidad para Visitantes en formato PDF (2 páginas)
para ABC GOTUPLAS S.A.S.
"""

import io
from datetime import datetime
from typing import Any

from PIL import Image as PILImage
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

MESES_ES = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre",
}


class NumberedCanvas(canvas.Canvas):
    """Canvas de dos pasos para numerar páginas con formato 'Página X de Y'."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            super().showPage()
        super().save()

    def draw_page_number(self, page_count: int) -> None:
        self.setFont("Helvetica", 9)
        self.drawRightString(
            letter[0] - 50,
            30,
            f"Página {self._pageNumber} de {page_count}",
        )


def _formatear_fecha(fecha_str: str | None) -> tuple[str, str, str]:
    if not fecha_str:
        hoy = datetime.now()
        return str(hoy.day), MESES_ES.get(hoy.month, "octubre"), str(hoy.year)
    try:
        dt = datetime.strptime(fecha_str.strip(), "%Y-%m-%d")
        return str(dt.day), MESES_ES.get(dt.month, "octubre"), str(dt.year)
    except ValueError:
        hoy = datetime.now()
        return str(hoy.day), MESES_ES.get(hoy.month, "octubre"), str(hoy.year)


def generar_acuerdo_pdf(
    registro: dict[str, Any],
    firma_bytes: bytes | None = None,
) -> bytes:
    """
    Genera el PDF del Acuerdo de Confidencialidad de 2 páginas con los datos
    del visitante y su firma digital estampada.
    """
    nombre = (registro.get("nombre") or "").strip()
    cedula = (registro.get("cedula") or "").strip()
    empresa = (registro.get("empresa") or "").strip()
    dia, mes, anio = _formatear_fecha(registro.get("fecha"))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=50,
        rightMargin=50,
        topMargin=36,
        bottomMargin=42,
    )

    title_style = ParagraphStyle(
        "TitleStyle",
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=13,
        alignment=1,
        spaceAfter=8,
    )
    body_style = ParagraphStyle(
        "BodyStyle",
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        alignment=4,
        spaceAfter=4,
    )
    list_style = ParagraphStyle(
        "ListStyle",
        fontName="Helvetica",
        fontSize=8.5,
        leading=10.5,
        leftIndent=15,
        spaceAfter=1.5,
    )

    story = []

    # ========================== PÁGINA 1 ==========================
    story.append(
        Paragraph("<u>ACUERDO DE CONFIDENCIALIDAD PARA VISITANTES</u>", title_style)
    )

    intro_texto = (
        "Entre los suscritos: <b>ABC GOTUPLAS S.A.S.</b>, identificada con NIT 830.006.911-3, "
        "con domicilio en Bogotá D.C., quien en adelante se denominará <b>LA EMPRESA</b>; "
        f"y <b>{nombre or '_____________________________'}</b>, "
        f"identificado(a) con C.C./Pasaporte No. <b>{cedula or '____________________'}</b>, "
        "actuando en calidad de <b>VISITANTE</b>, quien declara ingresar a las instalaciones "
        "de LA EMPRESA por motivos de visita técnica, comercial, industrial o de relacionamiento; "
        "se celebra el presente <b>ACUERDO DE CONFIDENCIALIDAD</b>, el cual se regirá por las siguientes cláusulas:"
    )
    story.append(Paragraph(intro_texto, body_style))

    story.append(
        Paragraph(
            "<b>PRIMERA. Objeto del Acuerdo.</b> El presente acuerdo tiene por objeto proteger toda la información "
            "confidencial, estratégica, técnica, operativa, industrial, comercial, documental y tecnológica a la que "
            "el VISITANTE tenga acceso durante su ingreso a las instalaciones de LA EMPRESA, incluyendo recorridos, "
            "reuniones, conversaciones, demostraciones, visitas guiadas o cualquier interacción con el personal.",
            body_style,
        )
    )

    story.append(
        Paragraph(
            "<b>SEGUNDA. Definición de Información Confidencial.</b> Se entenderá como información confidencial "
            "toda aquella relacionada con:",
            body_style,
        )
    )
    items_segunda = [
        "1. Procesos productivos, maquinaria, equipos, moldes, matrices y configuraciones técnicas.",
        "2. Procedimientos operativos, manuales internos, flujos de trabajo y métodos de fabricación.",
        "3. Información de inventarios, proveedores, clientes, precios, costos y estrategias comerciales.",
        "4. Sistemas de gestión, controles internos, indicadores, reportes y documentación interna.",
        "5. Infraestructura, distribución de planta, layout, seguridad industrial y logística.",
        "6. Conversaciones, explicaciones, datos, imágenes, videos o cualquier información observada o recibida.",
    ]
    for it in items_segunda:
        story.append(Paragraph(it, list_style))

    story.append(
        Paragraph(
            "La información confidencial incluye lo que el VISITANTE vea, escuche, observe, deduzca o registre, "
            "independientemente de su forma de presentación.",
            body_style,
        )
    )

    story.append(
        Paragraph(
            "<b>TERCERA. Obligaciones del VISITANTE.</b> El VISITANTE se obliga a:",
            body_style,
        )
    )
    items_tercera = [
        "1. Guardar absoluta reserva sobre toda la información confidencial.",
        "2. No divulgar, comunicar, transferir, publicar o compartir información con terceros.",
        "3. No tomar fotografías, videos, grabaciones o notas sin autorización previa y escrita de LA EMPRESA.",
        "4. No copiar, reproducir, analizar, desensamblar o intentar replicar procesos, maquinaria o procedimientos.",
        "5. No utilizar la información para fines comerciales, industriales, competitivos o de cualquier naturaleza.",
        "6. No ingresar con dispositivos de captura sin autorización (celulares, cámaras, tablets, gafas inteligentes, etc.).",
        "7. Cumplir las instrucciones de seguridad, acompañamiento y circulación dentro de la planta.",
    ]
    for it in items_tercera:
        story.append(Paragraph(it, list_style))

    story.append(
        Paragraph(
            "<b>CUARTA. Propiedad de la Información.</b> Toda la información observada, recibida o generada durante "
            "la visita es propiedad exclusiva de LA EMPRESA. El VISITANTE no adquiere ningún derecho sobre ella.",
            body_style,
        )
    )

    story.append(
        Paragraph(
            "<b>QUINTA. Prohibición de Competencia y Uso Indebido.</b> El VISITANTE se compromete a no:",
            body_style,
        )
    )
    story.append(
        Paragraph(
            "1. Utilizar la información para desarrollar productos, procesos o servicios similares.",
            list_style,
        )
    )
    story.append(
        Paragraph(
            "2. Entregar información a empresas competidoras o relacionadas.",
            list_style,
        )
    )

    # ========================== PÁGINA 2 ==========================
    story.append(PageBreak())

    story.append(
        Paragraph(
            "3. Realizar ingeniería inversa o análisis técnico de los procesos observados.",
            list_style,
        )
    )

    story.append(
        Paragraph(
            "<b>SEXTA. Responsabilidad e Indemnidad.</b> El VISITANTE será responsable por:",
            body_style,
        )
    )
    items_sexta = [
        "1. Cualquier daño, perjuicio o pérdida derivada del uso indebido de la información.",
        "2. Cualquier divulgación no autorizada, incluso si es accidental.",
        "3. El cumplimiento de este acuerdo por parte de cualquier persona que lo acompañe o represente.",
    ]
    for it in items_sexta:
        story.append(Paragraph(it, list_style))

    story.append(
        Paragraph(
            "El VISITANTE se obliga a mantener indemne a LA EMPRESA frente a reclamaciones, daños o "
            "perjuicios derivados del incumplimiento de este acuerdo.",
            body_style,
        )
    )

    story.append(
        Paragraph(
            "<b>SÉPTIMA. Duración de la Obligación.</b> La obligación de confidencialidad tendrá una vigencia de cinco "
            "(5) años, contados a partir de la firma del presente documento, independientemente de la duración o "
            "motivo de la visita.",
            body_style,
        )
    )

    story.append(
        Paragraph(
            "<b>OCTAVA. Devolución o Eliminación de Información.</b> Si el VISITANTE recibe documentos, muestras, "
            "fotografías autorizadas o cualquier material, deberá devolverlo o eliminarlo cuando LA EMPRESA lo solicite.",
            body_style,
        )
    )

    story.append(
        Paragraph(
            "<b>NOVENA. Sanciones y Acciones Legales.</b> El incumplimiento de este acuerdo faculta a LA EMPRESA para:",
            body_style,
        )
    )
    items_novena = [
        "1. Iniciar acciones civiles, comerciales o penales.",
        "2. Exigir indemnización por daños y perjuicios.",
        "3. Negar futuros ingresos a instalaciones o proyectos.",
    ]
    for it in items_novena:
        story.append(Paragraph(it, list_style))

    story.append(
        Paragraph(
            "<b>DÉCIMA. Aceptación.</b> El VISITANTE declara que:",
            body_style,
        )
    )
    items_decima = [
        "1. Ha leído y entendido el contenido del presente acuerdo.",
        "2. Firma de manera libre, voluntaria e informada.",
        "3. Acepta todas las obligaciones aquí contenidas.",
    ]
    for it in items_decima:
        story.append(Paragraph(it, list_style))

    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            f"En constancia, se firma en Bogotá D.C., a los <b>{dia}</b> días del mes de <b>{mes}</b> de <b>{anio}</b>.",
            body_style,
        )
    )
    story.append(Spacer(1, 10))

    story.append(
        Paragraph(
            "<b>LA EMPRESA</b><br/>"
            "ABC GOTUPLAS S.A.S.<br/>"
            "Nombre: __________________________<br/>"
            "Cargo: ___________________________",
            body_style,
        )
    )
    story.append(Spacer(1, 38))
    story.append(
        Paragraph(
            "<b>EL VISITANTE</b><br/>"
            f"Nombre: <b>{nombre or '__________________________'}</b><br/>"
            f"Documento: <b>{cedula or '_______________________'}</b><br/>"
            f"Empresa: <b>{empresa or '_________________________'}</b><br/>"
            "Firma digital:",
            body_style,
        )
    )

    if firma_bytes:
        try:
            img_stream = io.BytesIO(firma_bytes)
            pil_img = PILImage.open(img_stream)
            w, h = pil_img.size
            aspect = (h / w) if w > 0 else 0.25
            target_w = 150
            target_h = min(max(target_w * aspect, 25), 45)
            img_stream.seek(0)
            sig_img = Image(
                img_stream,
                width=target_w,
                height=target_h,
                hAlign="LEFT",
            )
            story.append(sig_img)
        except Exception:
            story.append(Paragraph("___________________________", body_style))
    else:
        story.append(Paragraph("___________________________", body_style))

    doc.build(story, canvasmaker=NumberedCanvas)
    return buffer.getvalue()
