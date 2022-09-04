from skimage import io
import numpy as np


img = io.imread("../samples/q1.png")
print(img.shape)
print(img[0, 0])

nrows, ncols, _ = img.shape
rows, cols = np.ogrid[:nrows, :ncols]
for row in range(nrows):
    for col in range(ncols):
        colors = img[row, col]
        if colors[0] < 32 or colors[0] > 37 or colors[1] > 204 or colors[1] < 200 or colors[2] > 154 or colors[2] < 150:
            img[row, col] = [255, 255, 255, 255]

io.imsave("../testImages/output/q1.png", img)
