# Paper Review AI Agent

Hệ thống đa tác nhân AI phân tích, phản biện và đánh giá bài báo khoa học dựa trên bằng chứng. Nhận xét có thể truy về trang PDF hoặc đoạn Word gốc.

**Công nghệ:** FastAPI · Next.js/Node.js · LangGraph · Groq API · SQLite · MarkItDown · Docker Compose.

## Clone và chạy thử bằng một dòng lệnh

Cài **Git**, cài và mở **Docker Desktop** (Linux containers). Mở **Git Bash, Bash hoặc PowerShell 7+** tại nơi muốn lưu dự án rồi dán đúng một dòng:

```bash
git clone https://github.com/AnhKietgs/Review-paper.git paper-review && cd paper-review && docker compose up -d --build --wait
```

Sau khi lệnh hoàn tất, mở **[http://localhost:3000](http://localhost:3000)**. Khi khởi động lần đầu với database trống, hệ thống **tự nạp sẵn 2 paper và bộ rubric**, không cần tải tài liệu lên, tạo rubric hay chạy lệnh seed riêng:

| Dữ liệu có sẵn | Nội dung |
|---|---|
| Paper chính | Nghiên cứu ứng dụng công cụ trí tuệ nhân tạo trong hỗ trợ người nước ngoài học tiếng Việt — PDF 9 trang |
| Paper đối chiếu | ChatGPT in Language Learning: Perspectives from Vietnamese Students in Vietnam and the USA — PDF 14 trang; trong ứng dụng có tiêu đề “nghiên cứu việc dùng ChatGPT hỗ trợ học ngôn ngữ trong bối cảnh sinh viên Việt Nam” |
| Rubric | **Review bài báo AI tiếng Việt**, gồm **6 tiêu chí** và hướng dẫn đánh giá theo đúng thứ tự |

Lần build đầu cần Internet để tải image và thư viện nên có thể mất vài phút. Thư mục `paper-review` cần chưa tồn tại; các cổng **3000** và **8000** cần còn trống.

| Địa chỉ | Chức năng |
|---|---|
| [localhost:3000](http://localhost:3000) | Giao diện sử dụng |
| [localhost:8000/docs](http://localhost:8000/docs) | Swagger / tài liệu REST API |
| [localhost:8000/api/v1/health](http://localhost:8000/api/v1/health) | Kiểm tra backend |

**Mặc định sau khi clone:** không cần `.env` hay API key để mở ứng dụng và xem dữ liệu có sẵn. Docker chạy chế độ `fixture` với kết quả mô phỏng để thử quy trình; 2 PDF và rubric vẫn là bộ dữ liệu thực tế đi kèm dự án. Muốn nhận xét do AI thật sinh ra, cấu hình Groq theo phần bên dưới.

Nếu đã tải code về, mở terminal tại thư mục có `compose.yaml` và chạy:

```bash
docker compose up -d --build --wait
```

Dữ liệu chia sẻ nằm trong `demo_data/library.json` và 2 file PDF đi kèm. Lần khởi động sau giữ nguyên dữ liệu và chỉnh sửa trên máy. Đặt `SEED_SAMPLE_DATA=0` trong `.env` nếu muốn khởi động với thư viện trống. Có thể nạp bổ sung bằng `docker compose exec -T backend python -m app.demo.seed`; lệnh bỏ qua paper trùng tiêu đề và rubric trùng tên.

## Thử một lượt review

1. Mở **Bản review** và tạo bản mới.
2. Chọn paper chính `Nghiên cứu ứng dụng công cụ trí tuệ nhân tạo trong hỗ trợ người nước ngoài học tiếng Việt` và rubric `Review bài báo AI tiếng Việt`.
3. Có thể chọn thêm `nghiên cứu việc dùng ChatGPT hỗ trợ học ngôn ngữ trong bối cảnh sinh viên Việt Nam` làm công trình đối chiếu.
4. Bắt đầu review, theo dõi agent và các bước xử lý trong màn hình tiến trình.
5. Khi hoàn tất, mở bản review, xem trích dẫn nguồn và tải báo cáo Markdown.

Bạn cũng có thể tải **PDF có lớp văn bản hoặc DOCX** trong **Thư viện paper**, tạo tiêu chí trong **Rubric đánh giá** rồi review tài liệu của mình. PDF scan chưa có OCR.

## Chạy AI thật bằng Groq

1. Sao chép `.env.example` thành `.env` tại thư mục gốc dự án.
2. Mở `.env` và điền:

   ```dotenv
   DEMO_LLM_MODE=groq
   GROQ_API_KEY=YOUR_GROQ_API_KEY
   ```

3. Áp dụng cấu hình backend:

   ```bash
   docker compose up -d --force-recreate backend
   ```

4. Tạo lượt review mới trong giao diện.

Docker đọc **`.env`**; sửa riêng `.env.example` sẽ không cập nhật cấu hình đang chạy. `.env` đã được Git bỏ qua; giữ API key trong file này.

| Agent | Model mặc định |
|---|---|
| Supervisor | `openai/gpt-oss-20b` |
| Scientific Review | `openai/gpt-oss-120b` |
| Related-Work Comparator | `openai/gpt-oss-20b` |
| Evidence Verifier | `openai/gpt-oss-20b` |

Tên biến đổi model nằm trong `.env.example`. Bộ điều phối quota mặc định dùng `GROQ_TOKENS_PER_MINUTE=8000` và `GROQ_REQUESTS_PER_MINUTE=30` cho mỗi model; điều chỉnh theo tài khoản của bạn. Nếu Groq trả 429, app giữ checkpoint và chờ theo `Retry-After`. Hạn mức token theo ngày vẫn có thể khiến thời gian chờ dài.

## Các lệnh thường dùng

Chạy tại thư mục gốc dự án:

| Việc cần làm | Lệnh |
|---|---|
| Xem trạng thái | `docker compose ps` |
| Xem log backend | `docker compose logs -f backend` |
| Build lại sau khi cập nhật code | `docker compose up -d --build --wait` |
| Nạp bộ paper và rubric chia sẻ | `docker compose exec -T backend python -m app.demo.seed` |
| Dừng ứng dụng, giữ dữ liệu | `docker compose down` |

Dữ liệu được lưu trong Docker volume `app_data`. Lệnh `docker compose down -v` sẽ xóa cả dữ liệu trong volume.

## Cách hệ thống hoạt động

**Tải tài liệu → trích xuất nội dung → chọn rubric và paper đối chiếu → Supervisor điều phối agent cần thiết → kiểm tra nguồn và bằng chứng → xuất báo cáo.**

Mini harness quản lý loop, tool, memory/checkpoint, context, permission, quota và output gate. Agent chọn `chunk_id` + `span_id`; hệ thống tự lấy nguyên văn trích dẫn, vị trí ký tự và trang/đoạn gốc. Evidence Verifier đánh giá bằng chứng có hỗ trợ nhận xét hay không. Nhận xét chưa đủ bằng chứng được ghi rõ trạng thái.

MVP chạy local với một backend worker. Paper đối chiếu do người dùng tải lên và lựa chọn; Literature Review và tìm kiếm Internet là hướng mở rộng.

## Cấu trúc và tài liệu

```text
backend/app/api/             REST controllers và schema
backend/app/domain/          Domain models và policies
backend/app/services/        CRUD, quản lý review và xuất báo cáo
backend/app/infrastructure/  Database, lưu file và Groq adapter
backend/app/ingestion/       Chuyển đổi PDF/DOCX và định vị nguồn
backend/app/agents/          Agent contracts, prompts và LangGraph
backend/app/harness/         Điều phối, context, permission và kiểm chứng
backend/app/workers/         Worker xử lý review
frontend/src/               Giao diện Next.js
demo_data/                  2 PDF thực tế và rubric chia sẻ (library.json)
docs/                       Tài liệu API và kiến trúc
```

Xem thêm [MVC/MVT và design patterns](docs/architecture/mvc.md), [thiết kế harness](docs/architecture/harness.md) và [REST API](docs/api/rest-contract.md).

## Kiểm tra khi phát triển

Backend — chạy tại thư mục gốc, cần Python 3.12+:

```bash
python -m pip install -e "./backend[dev]"
python -m pytest -c backend/pyproject.toml backend/tests -q
python -m pylint backend/app --rcfile=backend/pyproject.toml
python -m pycodestyle backend/app backend/tests backend/migrations
```

Frontend — chạy trong thư mục `frontend`, cần Node.js/npm:

```bash
npm ci
npm run lint
npm run build
```

Để chạy kiểm tra trình duyệt: cài browser bằng `npx playwright install chromium`, khởi động ứng dụng ở chế độ `fixture`, rồi chạy `npm run test:e2e` trong `frontend`.
