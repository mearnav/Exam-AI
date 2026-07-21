import fitz  # PyMuPDF — renders PDF pages to images
from google import genai
from google.genai import types
from src import config

client = genai.Client(api_key=config.GOOGLE_API_KEY)


def pdf_to_images(pdf_path: str, max_pages: int = 5) -> list[bytes]:
    """Render each PDF page into a PNG image (bytes). Vision models read
    images, not PDF pages — so we must convert first."""
    images = []
    doc = fitz.open(pdf_path)
    for page in doc[:max_pages]:
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        images.append(pix.tobytes("png"))
    doc.close()
    return images


def read_handwritten_pdf(pdf_path: str) -> str:
    """Use Gemini vision to read a handwritten/scanned answer sheet."""
    images = pdf_to_images(pdf_path)
    if not images:
        return ""

    prompt = (
        "This is a student's answer sheet. Transcribe ALL the text you can see, "
        "exactly as written — including the set name at the top, the student's "
        "name, and their answer for each question. For multiple-choice answers, "
        "record the option letter the student chose or circled. Do NOT correct "
        "or judge the answers — transcribe exactly what the student wrote. "
        "Preserve question numbers (Q1, Q2, ...)."
    )

    parts = [prompt]
    for img_bytes in images:
        parts.append(types.Part.from_bytes(data=img_bytes, mime_type="image/png"))

    try:
        response = client.models.generate_content(
            model=config.VISION_MODEL,
            contents=parts,
        )
        return response.text or ""
    except Exception as e:
        # Vision unavailable (quota, network, etc.) — signal failure cleanly
        print(f"[vision] unavailable: {e}")
        return "__VISION_UNAVAILABLE__"


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m src.vision <path-to-pdf>")
    else:
        text = read_handwritten_pdf(sys.argv[1])
        print("--- Vision transcription ---")
        print(text)