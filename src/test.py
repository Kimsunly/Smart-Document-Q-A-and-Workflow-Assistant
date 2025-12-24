from paddleocr import PaddleOCR

ocr = PaddleOCR(use_textline_orientation=True, lang='en')
result = ocr.ocr("data/images/sample.png")

for line in result[0]['rec_texts']:
    print(line)
