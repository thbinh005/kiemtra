import json
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "static"
DATA_FILE = Path(
	os.environ.get("STUDENT_DATA_FILE", ROOT / ".student-data" / "students.json")
)
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "5135"))


def read_students():
	if not DATA_FILE.exists():
		return []
	try:
		students = json.loads(DATA_FILE.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError) as error:
		raise RuntimeError("Không đọc được tệp dữ liệu sinh viên.") from error
	if not isinstance(students, list):
		raise RuntimeError("Tệp dữ liệu sinh viên không đúng định dạng.")
	return students


def write_students(students):
	DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
	temporary_file = DATA_FILE.with_suffix(".tmp")
	temporary_file.write_text(
		json.dumps(students, ensure_ascii=False, indent=2), encoding="utf-8"
	)
	temporary_file.replace(DATA_FILE)


class StudentHandler(BaseHTTPRequestHandler):
	def send_json(self, status, payload):
		body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
		self.send_response(status)
		self.send_header("Content-Type", "application/json; charset=utf-8")
		self.send_header("Content-Length", str(len(body)))
		self.send_header("Cache-Control", "no-store")
		self.end_headers()
		self.wfile.write(body)

	def do_GET(self):
		path = urlparse(self.path).path
		if path == "/api/students":
			try:
				self.send_json(200, {"students": read_students()})
			except RuntimeError as error:
				self.send_json(500, {"error": str(error)})
			return

		if path == "/":
			path = "/index.html"
		file_path = (WEB_ROOT / path.lstrip("/")).resolve()
		if not file_path.is_relative_to(WEB_ROOT) or not file_path.is_file():
			self.send_error(404, "Không tìm thấy trang")
			return

		content_type = (
			"text/html; charset=utf-8"
			if file_path.suffix == ".html"
			else "application/octet-stream"
		)
		body = file_path.read_bytes()
		self.send_response(200)
		self.send_header("Content-Type", content_type)
		self.send_header("Content-Length", str(len(body)))
		self.send_header("X-Content-Type-Options", "nosniff")
		self.end_headers()
		self.wfile.write(body)

	def do_POST(self):
		if urlparse(self.path).path != "/api/students":
			self.send_json(404, {"error": "Không tìm thấy đường dẫn."})
			return

		try:
			content_length = int(self.headers.get("Content-Length", "0"))
			if content_length <= 0 or content_length > 65536:
				self.send_json(400, {"error": "Dữ liệu gửi lên không hợp lệ."})
				return
			payload = json.loads(self.rfile.read(content_length))
			if not isinstance(payload, dict):
				self.send_json(400, {"error": "Dữ liệu gửi lên không hợp lệ."})
				return

			student_code = str(payload.get("studentCode", "")).strip()
			full_name = str(payload.get("fullName", "")).strip()
			gender = str(payload.get("gender", "")).strip()
			class_name = str(payload.get("className", "")).strip()
			if not student_code or not full_name or gender not in ("Nam", "Nữ"):
				self.send_json(
					400,
					{"error": "Vui lòng nhập mã, họ tên và giới tính hợp lệ."},
				)
				return
			if len(student_code) > 30 or len(full_name) > 100 or len(class_name) > 50:
				self.send_json(
					400, {"error": "Một trong các trường đã vượt quá độ dài cho phép."}
				)
				return

			students = read_students()
			if any(
				item.get("studentCode", "").casefold() == student_code.casefold()
				for item in students
			):
				self.send_json(409, {"error": "Mã sinh viên này đã tồn tại."})
				return

			student = {
				"id": str(uuid.uuid4()),
				"studentCode": student_code,
				"fullName": full_name,
				"gender": gender,
				"className": class_name,
			}
			students.append(student)
			write_students(students)
			self.send_json(201, {"student": student})
		except (ValueError, UnicodeDecodeError):
			self.send_json(400, {"error": "Nội dung gửi lên không phải JSON hợp lệ."})
		except RuntimeError as error:
			self.send_json(500, {"error": str(error)})
		except OSError:
			self.send_json(500, {"error": "Không thể lưu dữ liệu sinh viên."})

	def do_DELETE(self):
		parts = urlparse(self.path).path.strip("/").split("/")
		if len(parts) != 3 or parts[:2] != ["api", "students"]:
			self.send_json(404, {"error": "Không tìm thấy đường dẫn."})
			return
		try:
			students = read_students()
			remaining = [student for student in students if student.get("id") != parts[2]]
			if len(remaining) == len(students):
				self.send_json(404, {"error": "Không tìm thấy sinh viên."})
				return
			write_students(remaining)
			self.send_json(200, {"students": remaining})
		except RuntimeError as error:
			self.send_json(500, {"error": str(error)})
		except OSError:
			self.send_json(500, {"error": "Không thể cập nhật dữ liệu sinh viên."})

	def log_message(self, format_string, *args):
		print(f"{self.address_string()} - {format_string % args}")


if __name__ == "__main__":
	server = ThreadingHTTPServer((HOST, PORT), StudentHandler)
	print(f"Ứng dụng đang chạy tại http://{HOST}:{PORT}")
	try:
		server.serve_forever()
	except KeyboardInterrupt:
		print("\nĐã dừng máy chủ.")
	finally:
		server.server_close()
