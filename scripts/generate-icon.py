from pathlib import Path

from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1]
image = Image.new("RGBA", (256, 256))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((4, 4, 252, 252), radius=58, fill="#b8e994")
draw.polygon([(48, 121), (211, 48), (163, 212), (117, 153)], fill="#1d3214")
draw.polygon([(117, 153), (185, 77), (105, 133)], fill="#b8e994")
image.save(root / "desktop/icon.png")
image.save(root / "desktop/icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
