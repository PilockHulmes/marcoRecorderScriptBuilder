import easyocr

reader = easyocr.Reader(['ch_tra', 'en'])
result = reader.readtext('../testImages/question2.jpg', detail=0)
print(result)ggf
