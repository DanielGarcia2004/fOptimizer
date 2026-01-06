import sys
import subprocess
from pathlib import Path

import oxipng
import numpy as np
from sourcepp import vtfpp

from .misc import exception_logger

import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent
PNGQUANT_EXE = BASE_DIR / "pngquant" / "pngquant.exe"


def fit_alpha(vtf: vtfpp.VTF, output_file: Path, lossless: bool) -> bool:
    """
    Encodes the best alpha format for a supported encoding-encoded VTF image losslessly.
    
    :param vtf: The VTF to determine the optimal alpha format for.
    :type vtf: vtfpp.VTF
    :param output_file: The path of the VTF file to write to.
    :type output_file: Path
    :return: Whether the function completed successfully.
    :rtype: bool
    """

    try:
        format_name = vtf.format.name
        if format_name in ("DXT5", "DXT3", "DXT1_ONE_BIT_ALPHA"):
            return fit_dxt(vtf=vtf, output_file=output_file, lossless=lossless)
        elif format_name in ("BGRA8888", "RGBA8888", "ABGR8888", "ARGB8888", "BGRX8888"):
            return fit_8888(vtf=vtf, output_file=output_file)
        else:
            vtf.bake_to_file(str(output_file))
    except Exception:
        exception_logger(exc=Exception("fit_alpha failed"))
        return False
    

def fit_8888(vtf: vtfpp.VTF, output_file: Path) -> bool:
    """
    Encodes the best alpha format for a 8888 prefix-encoded VTF image losslessly.
    
    :param vtf: The VTF to determine the optimal alpha format for.
    :type vtf: vtfpp.VTF
    :param output_file: The path of the VTF file to write to.
    :type output_file: Path
    :return: Whether the function completed successfully.
    :rtype: bool
    """

    try:
        alpha_8888 = {"BGRA8888": "BGR888",
                      "RGBA8888": "RGB888",
                      }
        shift_8888 = {
            "ABGR8888": ("BGR888", 0, [1, 2, 3]), 
            "ARGB8888": ("RGB888", 2, [3, 0, 1]),
            }
        free_8888 = {"BGRX8888": "BGR888"}

        # where are these even used lol
        dudv_8888 = {"UVLX8888": "UV88",
                     "UVWQ8888": "UV88",
                     }

        format_name = vtf.format.name
        is_alpha = format_name in alpha_8888
        is_shift = format_name in shift_8888
        is_free = format_name in free_8888

        if not is_alpha and not is_shift:
            if is_free:
                target_format = getattr(vtfpp.ImageFormat, free_8888[format_name])
                vtf.set_format(target_format)
            vtf.bake_to_file(str(output_file))
            return True

        if is_alpha:
            target_format_name = alpha_8888[format_name]
            alpha_idx = 3
            swizzle = None
        else:
            target_format_name, alpha_idx, swizzle = shift_8888[format_name]

        target_format = getattr(vtfpp.ImageFormat, target_format_name)
        can_strip_alpha = True

        for i in range(vtf.frame_count):
            raw_data = np.frombuffer(vtf.get_image_data_raw(frame=i), dtype=np.uint8)
            pixels = raw_data.reshape(-1, 4)
            if np.any(pixels[:, alpha_idx] < 255):
                can_strip_alpha = False
                break

        if can_strip_alpha:
            if is_shift:
                frames = [np.frombuffer(vtf.get_image_data_raw(frame=i), dtype=np.uint8).copy() 
                        for i in range(vtf.frame_count)]
                
                vtf.set_format(target_format)
                
                for i, raw_data in enumerate(frames):
                    pixels = raw_data.reshape(-1, 4)
                    stripped = pixels[:, swizzle].flatten()
                    
                    try:
                        vtf.set_image(
                            image_data=stripped.tobytes(),
                            format=target_format,
                            width=vtf.width,
                            height=vtf.height,
                            filter=vtfpp.ImageConversion.ResizeFilter.NICE,
                            mip=0,
                            frame=i
                        )
                    except Exception as e:
                        print(f"Error: {e}")
            else:
                vtf.set_format(target_format)
        
        vtf.bake_to_file(str(output_file))
        return True

    except Exception:
        exception_logger(exc=Exception("fit_8888 failed"))
        return False
    

def fit_dxt(vtf: vtfpp.VTF, output_file: Path, lossless: bool) -> bool:
    """
    Encodes the best alpha format for a DXT-encoded VTF image "losslessly."
    
    :param vtf: The VTF to determine the optimal alpha format for.
    :type vtf: vtfpp.VTF
    :param output_file: The path of the VTF file to write to.
    :type output_file: Path
    :return: Whether the function completed successfully.
    :rtype: bool
    """

    try:
        if vtf.format.name not in ("DXT5", "DXT3", "DXT1_ONE_BIT_ALPHA"):
            vtf.bake_to_file(str(output_file))
            return True

        original_format = vtf.format
        translucent = False
        bi_trans = False
        crushed = False

        for i in range(vtf.frame_count):
            vtf.set_format(original_format)

            original_rgba = np.frombuffer(vtf.get_image_data_as_rgba8888(frame=i), dtype=np.uint8).copy()
            alpha = original_rgba[3::4]

            if np.all(alpha == 0):
                # stops images with fully transparent alpha channels (for specularity?) being exported completely black
                vtf.set_format(original_format)
                vtf.bake_to_file(str(output_file))
                return True

            if np.any((alpha > 0) & (alpha < 255)):
                translucent = True
                break
            
            if np.any(alpha == 0):
                bi_trans = True

            if bi_trans and lossless:
                vtf.set_format(vtfpp.ImageFormat.DXT1_ONE_BIT_ALPHA)
                test_rgba = np.frombuffer(vtf.get_image_data_as_rgba8888(frame=i), dtype=np.uint8)

                if not np.array_equal(original_rgba, test_rgba):
                    crushed = True
                    break
            
        if translucent:
            vtf.set_format(original_format)
        elif bi_trans:
            if crushed:
                vtf.set_format(original_format)
            else:
                vtf.set_format(vtfpp.ImageFormat.DXT1_ONE_BIT_ALPHA)
        else:
            vtf.set_format(vtfpp.ImageFormat.DXT1)

        vtf.bake_to_file(str(output_file))
        return True
    
    except Exception:
        exception_logger(exc=Exception("fit_dxt failed"))
        return False


def is_normal(vtf: vtfpp.VTF) -> bool:
    """
    Attempts to determine if a VTF image is supposed to be a normal/bump map.
    
    :param vtf: The VTF to be evaluated.
    :type vtf: vtfpp.VTF
    :return: Whether the VTF image appears to be a normal/bump map.
    :rtype: bool
    """

    try:
        image_data = vtf.get_image_data_as_rgba8888()
        pixels = np.frombuffer(image_data, dtype=np.uint8).astype(float) / 127.5 - 1.0
        pixels = pixels.reshape(-1, 4)[:, :3]

        magnitudes = np.linalg.norm(pixels, axis=1)
        
        avg_mag = np.mean(magnitudes)
        return 0.85 <= avg_mag <= 1.1
    except Exception:
        exception_logger(exc=Exception("is_normal failed"))
        return False


def shrink_solid(vtf: vtfpp.VTF, output_file: Path) -> bool:
    """
    Shrinks a solid-colour VTF into a 4x4 equivalent.
    
    :param vtf: The VTF to be evaluated if shrinking is possible.
    :type vtf: vtfpp.VTF
    :param output_file: The path of the VTF file to write to. 
    :type output_file: Path
    :return: Whether the function completed successfully.
    :rtype: bool
    """

    try:
        image_data = vtf.get_image_data_as_rgba8888()
        pixels = np.frombuffer(image_data, dtype=np.uint8).reshape(-1, 4)
        is_solid = np.all(pixels == pixels[0], axis=0).all()

        if is_solid:
            vtf.set_size(4, 4, vtfpp.ImageConversion.ResizeFilter.NICE)
        
        vtf.bake_to_file(str(output_file))

        return True
    except Exception:
        exception_logger(exc=Exception("shrink_solid failed"))
        return False


def resize_vtf(vtf: vtfpp.VTF, output_file: Path, w: int, h: int) -> bool:
    """
    Resizes and writes a VTF image.
    
    :param vtf: The VTF to be resized.
    :type vtf: vtfpp.VTF
    :param output_file: The resized VTF to be written to.
    :type output_file: Path
    :param w: The width of the resized VTF.
    :type w: int
    :param h: The height of the resized VTF.
    :type h: int
    :return: Whether the function completed successfully.
    :rtype: bool
    """

    try:

        if (vtf.width == w) and (vtf.height == h):
            return
        
        original_format = vtf.format

        vtf.set_format(vtfpp.ImageFormat.RGBA32323232F) # will crash without a conversion, but at least uses a lossless format (very memory heavy)
        
        vtf.set_size(w, h, vtfpp.ImageConversion.ResizeFilter.NICE) # why do 2:1 (w:h) images crash set_size()?

        vtf.set_format(original_format)

        vtf.bake_to_file(str(output_file))

        return True
    except Exception:
        exception_logger(exc=Exception("resize_vtf failed"))
        return False


def optimize_png(input_file: Path, output_file: Path, level: int = 100, lossless: bool = True) -> bool:
    """
    Optimizes a PNG image using oxipng.
    
    :param input_file: The PNG file to optimize.
    :type input_file: Path
    :param output_file: The optimized PNG file to write to.
    :type output_file: Path
    :param level: The normalized "intensity" of compression and comparisons. 0 => fastest, largest filesizes. 100 => slowest, smallest filesizes.
    :type level: int
    :return: Whether the function completed successfully.
    :rtype: bool
    """

    try:
        if lossless:
            oxipng.optimize(
                input_file, 
                output_file, 
                level=round(6/100 * level),
                force=True,
                optimize_alpha=True,
                strip=oxipng.StripChunks.all(),
                bit_depth_reduction=True,
                color_type_reduction=True,
                palette_reduction=True,
                scale_16=True
            )
        else:
            command = [
                str(PNGQUANT_EXE),
                str(input_file),
                "-f",
                "-o", str(output_file),
                "--speed", str(max(1, 11 - round(10/100 * level))),
                "--quality", f"0-{max(1, int(level))}",
                "--strip",
            ]
            subprocess.run(command, check=True, capture_output=True, text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)
            
        if output_file.exists():
            if input_file.stat().st_size <= output_file.stat().st_size:
                output_file.write_bytes(input_file.read_bytes())
        else:
            output_file.write_bytes(input_file.read_bytes())
        
        return True
    except Exception as e:
        print(e)
        exception_logger(exc=Exception("optimize_png failed"))
        return False