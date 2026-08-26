import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mnemodex.gif import Canvas, GifWriter, _lzw_encode, render_demo_gif


class LzwTest(unittest.TestCase):
    def test_known_vector(self):
        # The classic GIF LZW example: indices where min-code-size=2.
        indices = [0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3]
        out = _lzw_encode(indices, 2)
        self.assertIsInstance(out, bytes)
        self.assertGreater(len(out), 0)

    def test_deterministic(self):
        indices = list(range(8)) * 3
        self.assertEqual(_lzw_encode(indices, 3), _lzw_encode(indices, 3))

    def test_empty(self):
        self.assertEqual(_lzw_encode([], 2), b"")  # clear code + eoi only → handled upstream


class GifWriterTest(unittest.TestCase):
    def test_structure(self):
        w = GifWriter(10, 10)
        w.add_frame([0] * 100, delay_cs=8)
        data = w.build([(0, 0, 0), (255, 255, 255)])
        self.assertTrue(data.startswith(b"GIF89a"))
        self.assertTrue(data.endswith(b"\x3b"))
        # NETSCAPE loop present
        self.assertIn(b"NETSCAPE2.0", data)
        # width/height little-endian
        self.assertEqual(data[6], 10)
        self.assertEqual(data[8], 10)


class CanvasTest(unittest.TestCase):
    def test_size_and_text(self):
        c = Canvas(120, 40)
        c.text(2, 2, "HI", (255, 255, 255))
        indices, palette = c.to_indices()
        self.assertEqual(len(indices), 120 * 40)
        self.assertEqual(palette[0], (13, 17, 23))  # background first


class DemoRenderTest(unittest.TestCase):
    def test_render_small(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = render_demo_gif(os.path.join(d, "demo.gif"), width=640, height=360, fps=10, frames=60)
            self.assertTrue(os.path.exists(path))
            self.assertGreater(os.path.getsize(path), 500)
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(6), b"GIF89a")


if __name__ == "__main__":
    unittest.main()