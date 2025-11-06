# 解密 .jsc 文件 ，参考链接 https://bbs.kanxue.com/thread-283299.htm

# pip install xxtea-py
# pip install jsbeautifier
 
import xxtea
import gzip
import jsbeautifier
import os
import argparse

# 解密密钥
KEY = ""

# 默认输入目录（跨平台写法）
DEFAULT_INPUT_DIR = os.path.join("build/android/data", "assets")

# 运行时会根据传入参数计算 input_dir 与 output_dir
input_dir = DEFAULT_INPUT_DIR
output_dir = os.path.join(os.path.dirname(os.path.abspath(DEFAULT_INPUT_DIR)), "output")

def _parse_args():
    parser = argparse.ArgumentParser(description="Decrypt/Encrypt cocos2d-js .jsc files with XXTEA + gzip")
    parser.add_argument(
        "-i", "--input",
        dest="input_dir",
        default=DEFAULT_INPUT_DIR,
        help="输入目录，包含 .jsc 文件的 assets 目录；未设置时使用默认值"
    )
    parser.add_argument(
        "-o", "--output",
        dest="output_dir",
        default=None,
        help="输出目录；未设置时为输入目录同级的 output 目录"
    )
    return parser.parse_args()

def _init_paths():
    global input_dir, output_dir
    args = _parse_args()
    input_dir = os.path.abspath(args.input_dir)
    # 输出目录未传时，默认使用输入目录同级的 output
    output_dir = os.path.abspath(args.output_dir) if args.output_dir else os.path.join(os.path.dirname(input_dir), "output")
    # 确保输出根目录存在
    os.makedirs(output_dir, exist_ok=True)
 
def jscDecrypt(data: bytes, needJsBeautifier = True):
    dec = xxtea.decrypt(data, KEY)
    if not dec:
        raise ValueError("XXTEA 解密失败：可能是 KEY 不正确或文件不是有效的 .jsc")

    def _is_gzip(buf: bytes) -> bool:
        return len(buf) >= 2 and buf[0] == 0x1F and buf[1] == 0x8B

    def _safe_decode(buf: bytes) -> str:
        try:
            return buf.decode("utf-8")
        except UnicodeDecodeError:
            return buf.decode("utf-8", errors="replace")

    if _is_gzip(dec):
        try:
            jscode = gzip.decompress(dec).decode("utf-8")
        except gzip.BadGzipFile:
            # 兜底：尝试 zlib 格式，再不行直接按文本解码
            import zlib
            try:
                jscode = zlib.decompress(dec, wbits=15 + 32).decode("utf-8")
            except Exception:
                jscode = _safe_decode(dec)
    else:
        # 非 gzip，直接作为文本解码
        jscode = _safe_decode(dec)

    if needJsBeautifier:
        return jsbeautifier.beautify(jscode)
    else:
        return jscode
 
def jscEncrypt(data, compress: bool = True):
    raw = data.encode("utf-8")
    if compress:
        raw = gzip.compress(raw)
    enc = xxtea.encrypt(raw, KEY)
    return enc
 
def decryptAll():
    for root, dirs, files in os.walk(input_dir):
         
        # 創建與input_dir一致的結構
        for dir in dirs:
            dir_path = os.path.join(root, dir)
            target_dir = output_dir + dir_path.replace(input_dir, "")
            if not os.path.exists(target_dir):
                os.makedirs(target_dir, exist_ok=True)
 
        for file in files:
            file_path = os.path.join(root, file)
        
            if not file.endswith(".jsc"):
                continue
             
            with open(file_path, mode = "rb") as f:
                enc_jsc = f.read()
             
            dec_jscode = jscDecrypt(enc_jsc)
             
            output_file_path = output_dir + file_path.replace(input_dir, "").replace(".jsc", "") + ".js"
 
            # 确保父目录存在
            os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
            print(output_file_path)
            with open(output_file_path, mode = "w", encoding = "utf-8") as f:
                f.write(dec_jscode)
 
def decryptOne(path):
    with open(path, mode = "rb") as f:
        enc_jsc = f.read()
     
    dec_jscode = jscDecrypt(enc_jsc, False)
 
    output_path = path.split(".jsc")[0] + ".js"
 
    with open(output_path, mode = "w", encoding = "utf-8") as f:
        f.write(dec_jscode)
 
def encryptOne(path):
    with open(path, mode = "r", encoding = "utf-8") as f:
        jscode = f.read()
 
    enc_data = jscEncrypt(jscode)
     
    output_path = path.split(".js")[0] + ".jsc"
 
    with open(output_path, mode = "wb") as f:
        f.write(enc_data)
 
if __name__ == "__main__":
    _init_paths()
    decryptAll()