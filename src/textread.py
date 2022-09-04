import easyocr

reader = easyocr.Reader(['ch_tra'])
result = reader.readtext(
    '../testImages/output/q1.png', detail=0)
print(result)
