# Design and Development of an Evidence-Grounded Multi-Agent System for Scientific Paper Review

**Tên tiếng Việt:** Xây dựng hệ thống đa tác nhân AI hỗ trợ phân tích, phản biện và đánh giá bài báo khoa học dựa trên bằng chứng.

Ngày: 2026-10-26  
Trạng thái: Đã được người dùng chốt ngày 2026-10-26; chuyển sang lập kế hoạch triển khai M1–M6

## 1. Mục đích và phạm vi

Xây dựng ứng dụng web hỗ trợ người học/người nghiên cứu **phân tích và phản biện một bài báo khoa học** theo rubric có thể chỉnh sửa. Hệ thống rút trích mục tiêu, phương pháp, kết quả và đóng góp được tác giả tuyên bố; đánh giá phương pháp, hạn chế và chỗ thiếu bằng chứng; so sánh với những công trình liên quan **do người dùng tải lên và lựa chọn**; cuối cùng tạo Paper Review report. Mỗi nhận xét quan trọng phải truy xuất được tới đoạn và trang của paper nguồn. Người dùng quyết định bản cuối. Chỉ sau khi Paper Review vận hành ổn định, hệ thống mở rộng thành **Literature Review nhiều paper theo một câu hỏi nghiên cứu**. Việc **tự động tìm paper trên Internet** là nâng cấp sau đó, tách khỏi hai bản đầu.

Đây là công cụ hỗ trợ đánh giá, không tự đưa ra quyết định nhận/từ chối bài báo. Mọi kết luận của AI được hiển thị như bản nháp cần kiểm tra.

## 2. Mục tiêu, ngoài phạm vi, điều cần tránh

### Mục tiêu giai đoạn 1

- MVP là ứng dụng demo cục bộ cho một người dùng, không có đăng nhập. Mọi Paper, Rubric, Review và Run thuộc cùng một thư viện cục bộ; permission của harness giới hạn theo run và tập tài liệu được chọn, không dùng để phân quyền giữa nhiều tài khoản.
- Quản lý Paper, Rubric và Review Draft với CRUD đầy đủ qua REST API và giao diện.
- Tải PDF có lớp văn bản và DOCX, chuyển nội dung sang Markdown bằng MarkItDown, rồi lưu các đoạn có ID và vị trí nguồn ổn định để dẫn chứng.
- Tạo bản phân tích có cấu trúc gồm: mục tiêu, phương pháp, kết quả, đóng góp được tuyên bố, điểm mạnh, hạn chế và vấn đề cần kiểm chứng.
- Có đúng bốn vai trò agent: **Supervisor Agent** điều phối và quyết định vòng lặp, **Scientific Review Agent** phân tích/phản biện paper, **Related-Work Comparator** đối chiếu paper do người dùng chọn, và **Evidence Verifier** kiểm tra dẫn chứng. Các worker **chỉ được gọi khi Supervisor cần**, từng agent một, không chạy đồng loạt. Report Composer là service ghép dữ liệu đã qua gate theo mẫu cố định, không tính là agent.
- Cho phép người dùng tải các công trình liên quan lên cùng thư viện, chọn chúng cho từng review và đối chiếu với paper chính. Nếu không chọn nguồn đối chiếu, phần so sánh ghi `not_assessed`; không suy đoán từ danh mục tài liệu tham khảo.
- Harness do nhóm xây sở hữu vòng lặp xử lý tài liệu theo batch, tool registry, memory, context assembly, permission gate, output validation và event trace; LangGraph biểu diễn state graph của Supervisor và các worker. Thiết kế loop/tool/context tham khảo Hermes Agent ở mức ý tưởng, không sao chép runtime hay dùng Hermes làm framework.
- Cho phép xem trạng thái, từng bước xử lý, tool call, quyết định permission và lý do một nhận xét bị chặn hoặc cần sửa.
- Có bước người dùng duyệt/chỉnh sửa trước khi chốt bản review.
- Pylint và PEP 8 là cổng chất lượng bắt buộc cho Python; kiểm thử API và harness.

### Mục tiêu giai đoạn 2: Literature Review

- Tạo một Review Project với câu hỏi nghiên cứu và tập nhiều paper.
- Trích xuất, so sánh, nhóm luận điểm và tạo bản tổng quan có nguồn cho từng phát biểu.
- Tái sử dụng bốn agent/harness; mở rộng nhiệm vụ Related-Work Comparator để tổng hợp theo chủ đề trên tập nhiều paper, không thêm agent thứ năm trong bản đầu Literature Review.

### Nâng cấp sau Literature Review

- Tự động tìm paper trên Internet theo câu hỏi nghiên cứu; hiển thị nguồn, metadata và lý do đề xuất để người dùng chọn trước khi thêm vào thư viện hoặc một Review Project.
- Adapter tìm kiếm, điều kiện truy cập nguồn và chính sách lọc trùng sẽ có đặc tả riêng sau khi hai luồng dùng paper do người dùng cung cấp đã ổn định.

### Ngoài phạm vi ban đầu

- Tự động tìm paper trên Internet trong MVP và Literature Review bản đầu; crawler, đánh giá đạo văn, OCR cho PDF scan, Word `.doc` cũ, công bố review ra tạp chí.
- Đăng nhập, phân quyền nhiều người dùng hoặc nhiều tổ chức, và quy trình phản biện ẩn danh của tạp chí.
- Cam kết AI có thể xác minh tính đúng đắn khoa học chỉ từ nội dung PDF.
- Tự khẳng định tính mới tuyệt đối của paper so với toàn bộ lĩnh vực khi chưa có tập tài liệu đối chiếu đủ rộng.

### Điều cần tránh

- Agent tự gọi tool hoặc Groq mà bỏ qua harness và permission gate.
- Nhận xét không có dẫn chứng nhưng vẫn được đánh dấu là đã xác minh.
- Dùng dẫn chứng chỉ từ paper chính để kết luận về nội dung của một paper liên quan, hoặc trình bày so sánh với tập paper do người dùng chọn như kết luận về toàn bộ lĩnh vực.
- Logic nghiệp vụ nằm trong FastAPI route hoặc React component.
- Đánh đồng trace của LangGraph với toàn bộ harness tự xây.

## 3. Ràng buộc và quyết định công nghệ

| Khu vực | Quyết định |
|---|---|
| Backend | Python + FastAPI; API version `/api/v1`; Pydantic schema; SQLAlchemy repository |
| Frontend | Node.js + Next.js/React, gọi REST API của FastAPI |
| Agent | LangGraph Python cho state graph; không cho graph node gọi tool trực tiếp ngoài harness |
| LLM | Groq API qua adapter; model ID cấu hình bằng môi trường, chọn model hỗ trợ schema theo khả năng hiện có |
| Lưu trữ MVP | SQLite cho demo cục bộ; tách repository và migration để có thể đổi PostgreSQL |
| Tài liệu MVP | PDF có lớp văn bản và DOCX; MarkItDown chuẩn hóa sang Markdown. Tệp gốc lưu cục bộ, Markdown, metadata và bản đồ vị trí nguồn lưu DB |
| Chất lượng | Pylint, PEP 8, pytest, kiểm thử REST, kiểm thử permission/output/loop, lint frontend |
| Bí mật | API key chỉ ở backend qua biến môi trường; không đưa vào frontend, trace hay log |
| Phạm vi triển khai đầu tiên | Kế hoạch triển khai chi tiết kế tiếp chỉ bao phủ M1–M6 (Paper Review MVP); M7 và M8 có đặc tả/kế hoạch riêng sau khi MVP đạt cổng ổn định |
| Chạy local/demo | Docker Compose là cách chạy chính: `frontend` (Next.js) + `backend` (FastAPI/worker), SQLite và upload trong named volume; không cần container DB riêng |

Tài liệu chính thức hỗ trợ lựa chọn: [FastAPI APIRouter](https://fastapi.tiangolo.com/tutorial/bigger-applications/), [LangGraph](https://docs.langchain.com/oss/python/learn), [Groq Structured Outputs](https://console.groq.com/docs/structured-outputs), [Groq Rate Limits](https://console.groq.com/docs/rate-limits), [Hermes Agent loop](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/agent-loop.md), [MarkItDown](https://github.com/microsoft/markitdown/blob/main/README.md).

## 4. Các phương án đã cân nhắc

1. **Paper Review với nguồn đối chiếu do người dùng chọn, rồi Literature Review, rồi tìm kiếm tự động — được chọn.** Có luồng dọc hoàn chỉnh để kiểm chứng CRUD, harness và chất lượng dẫn chứng. Giai đoạn 2 thêm dự án tổng quan và agent tổng hợp trên nền dữ liệu đã có; tìm kiếm Internet là nâng cấp tiếp theo.
2. **Làm hai loại review ngay từ đầu.** Demo đầy đủ hơn nhưng làm mờ ranh giới giữa phản biện một paper và tổng hợp tài liệu; nhiều CRUD, prompt và kiểm thử cùng lúc.
3. **Chỉ dùng LangGraph làm toàn bộ runtime.** Nhanh hơn, nhưng khó chứng minh harness do nhóm tự xây sở hữu loop, permission và output gate như yêu cầu đề tài.

Quyết định 1 xuất phát từ lựa chọn của người dùng. Việc dùng Next.js, SQLite và PDF văn bản là đề xuất triển khai để giảm độ phức tạp của bản demo; có thể đổi nếu điều kiện môn học yêu cầu khác.

## 5. Kiến trúc MVC và design pattern

```text
Next.js View
  -> FastAPI Router/Controller
    -> Application Service (use case)
      -> Domain Model + Repository interface
      -> Harness facade
        -> LangGraph agent graph
        -> Groq adapter / tool adapters
    -> SQLAlchemy repository + file store
```

- **Model:** Paper, PaperChunk, SourceLocator, Rubric, Criterion, ReviewDraft, ReviewFinding, ReviewRun, RunEvent và các quy tắc trạng thái.
- **View:** trang quản lý paper/rubric, màn hình chạy review, timeline harness, trang xem và duyệt bản nháp.
- **Controller:** FastAPI router chỉ xác thực input, gọi application service và ánh xạ response/status code.
- **Repository pattern:** tách truy cập dữ liệu khỏi service để kiểm thử và đổi DB.
- **Adapter pattern:** cô lập Groq, MarkItDown/SourceLocator và storage; đổi provider hoặc bộ chuyển đổi không đổi domain.
- **Strategy pattern:** rubric và cách đánh giá theo tiêu chí có thể thay đổi mà không đổi luồng chính.
- **Factory pattern:** tạo agent graph theo cấu hình/rubric; không tạo đối tượng rải rác trong route.
- **State pattern (qua trạng thái miền):** chuyển trạng thái ReviewRun và ReviewDraft có quy tắc rõ ràng.

Không cần dựng framework MVC riêng. Tài liệu kiến trúc và cây thư mục phải cho thấy ranh giới MVC/MVT rõ ràng; frontend dùng View, backend dùng Model + Controller và service.

### Cây thư mục dự kiến cho MVP (M1–M6)

```text
project03/                       # thư mục dự án hiện tại
├─ README.md
├─ .gitignore                    # bỏ qua .env, cache; không chứa dữ liệu volume
├─ .env.example                  # DEMO_LLM_MODE, GROQ_API_KEY, cấu hình demo
├─ compose.yaml                  # frontend, backend, app_data volume, healthcheck
├─ demo_data/                   # PDF/DOCX mẫu và kết quả kỳ vọng, không chứa key
├─ docs/
│  ├─ architecture/              # MVC, luồng agent, harness, ERD
│  ├─ api/                       # hợp đồng REST và ví dụ request/response
│  ├─ evaluation/                # rubric đánh giá, baseline, kết quả M6E
│  └─ superpowers/               # bản thiết kế và kế hoạch thực thi
├─ backend/
│  ├─ Dockerfile                 # image Python/FastAPI
│  ├─ .dockerignore
│  ├─ docker/entrypoint.sh       # migration rồi khởi động API + worker
│  ├─ pyproject.toml             # FastAPI, LangGraph, Groq, MarkItDown, Pylint
│  ├─ alembic.ini
│  ├─ migrations/               # phiên bản schema DB
│  ├─ app/
│  │  ├─ main.py                # khởi tạo FastAPI, gắn router
│  │  ├─ core/                  # cấu hình, logging, xử lý lỗi
│  │  ├─ api/v1/
│  │  │  ├─ controllers/        # Paper, Rubric, Review, Run, Export
│  │  │  └─ schemas/            # Pydantic request/response
│  │  ├─ domain/
│  │  │  ├─ models/             # Paper, Chunk, Locator, Rubric, Review, Run
│  │  │  ├─ policies/           # quy tắc trạng thái, approval
│  │  │  └─ repositories/       # interface repository
│  │  ├─ services/              # use case CRUD, chạy review, duyệt, export
│  │  ├─ ingestion/
│  │  │  ├─ markitdown_adapter.py
│  │  │  ├─ pdf_locator.py
│  │  │  ├─ docx_locator.py
│  │  │  └─ chunker.py
│  │  ├─ harness/
│  │  │  ├─ runner.py           # loop, budget, chọn một worker mỗi turn
│  │  │  ├─ document_queue.py   # batch/checkpoint, phạm vi tài liệu
│  │  │  ├─ context.py          # context builder
│  │  │  ├─ memory.py           # state và progress của run
│  │  │  ├─ tool_gateway.py     # registry, dispatch, permission
│  │  │  ├─ output_gate.py      # kiểm tra schema và dẫn chứng
│  │  │  └─ events.py           # trace cho inspector
│  │  ├─ agents/
│  │  │  ├─ supervisor.py
│  │  │  ├─ scientific_review.py
│  │  │  ├─ related_work.py
│  │  │  ├─ evidence_verifier.py
│  │  │  ├─ graph_factory.py    # Factory tạo LangGraph subgraph
│  │  │  └─ prompts/            # prompt theo vai trò, version rõ ràng
│  │  ├─ infrastructure/
│  │  │  ├─ persistence/        # SQLAlchemy models, repository adapters
│  │  │  ├─ groq/               # Groq adapter
│  │  │  └─ storage/            # lưu PDF/DOCX/Markdown cục bộ
│  │  ├─ workers/run_worker.py  # một run nền đang chạy, resume checkpoint
│  │  └─ demo/seed.py           # nạp rubric và dữ liệu mẫu trong container
│  └─ tests/
│     ├─ api/                   # CRUD, REST status, validation
│     ├─ ingestion/             # PDF/DOCX -> Markdown -> locator
│     ├─ harness/               # loop, quyền, on-demand, trace
│     └─ agents/                # output schema và mock Groq
└─ frontend/
   ├─ Dockerfile                # image Node.js/Next.js
   ├─ .dockerignore
   ├─ package.json
   ├─ src/app/                  # Next.js routes: library, rubric, review, runs
   ├─ src/components/
   │  ├─ library/               # upload và chọn paper
   │  ├─ rubric/                # CRUD rubric
   │  ├─ review/                # findings, dẫn chứng, approval
   │  └─ harness/               # sơ đồ trạng thái và timeline
   └─ src/lib/api/              # REST client và kiểu dữ liệu
```

`app_data` là **Docker named volume** khai báo trong `compose.yaml`, gắn vào backend để giữ SQLite, tệp tải lên, Markdown và checkpoint. Nó không phải một thư mục nằm trong cây mã nguồn. `.env` được tạo cục bộ từ `.env.example` và bị `.gitignore` loại khỏi Git.

Ánh xạ **MVC**: `backend/app/domain/models` là Model; `backend/app/api/v1/controllers` là Controller; `frontend/src/app` và `components` là View. `services` giữ use case để Controller mỏng. Repository interface nằm trong domain, hiện thực SQLAlchemy nằm trong infrastructure; Groq và MarkItDown là Adapter. `agents/graph_factory.py` thể hiện Factory; rubric và approval policy nằm ở domain. Harness nằm riêng để chứng minh loop, tool, memory, context, permission và output gate là phần nhóm tự xây.

Các thư mục này là **thiết kế đã được duyệt**; việc tạo mã nguồn thuộc kế hoạch triển khai M1–M6.

## 6. Dữ liệu và REST API giai đoạn 1

### Thực thể

- `Paper`: id, title, authors, year, doi (nếu có), original_filename, media_type, file_path, content_version, conversion_status, created_at, updated_at, deleted_at. `media_type` chỉ nhận PDF hoặc DOCX ở MVP.
- `PaperChunk`: id, paper_id, content_version, order_index, markdown_text, text_hash, markdown_start, markdown_end. Khi thay tài liệu, tạo phiên bản nội dung mới để review cũ không trỏ sai nguồn.
- `SourceLocator`: chunk_id, locator_type (`pdf_page` hoặc `docx_paragraph`), locator_value, quote, source_file_hash. PDF dùng số trang; DOCX dùng đoạn/heading vì số trang phụ thuộc phần mềm dàn trang. Markdown chỉ là bản chuẩn hóa để xử lý, không thay thế vị trí nguồn gốc.
- `Rubric`: id, name, description, version, criteria, created_at, updated_at, deleted_at.
- `Criterion`: id, rubric_id, code, question, guidance, order_index. Giai đoạn 1 đánh giá định tính, không tính điểm tổng hợp.
- `ReviewDraft`: id, paper_id, rubric_id, rubric_version, revision, parent_revision_id, status, analysis, summary, findings, reviewer_edits, created_at, updated_at, deleted_at. Chạy lại tạo revision mới; bản đã sửa giữ nguyên để đối chiếu.
- `ReviewReference`: review_id, paper_id, paper_content_version. Lưu tập công trình đối chiếu mà người dùng đã chọn cho review; không tự thay đổi khi thư viện paper được cập nhật.
- `ReviewRun`: id, review_id, status, step_count, token/call usage nếu Groq trả về, started_at, finished_at, error_code.
- `RunEvent`: run_id, sequence, agent, action, tool, permission_result, input_summary, output_summary, timestamp. Trace không lưu API key hoặc nguyên văn prompt chứa dữ liệu không cần thiết.

### Endpoint

| Tài nguyên | Endpoint | Hành vi |
|---|---|---|
| Papers | `GET/POST /papers`, `GET/PATCH/DELETE /papers/{id}` | CRUD; tạo paper qua multipart PDF/DOCX + metadata; hiển thị Markdown và vị trí nguồn |
| Rubrics | `GET/POST /rubrics`, `GET/PATCH/DELETE /rubrics/{id}` | CRUD; sửa rubric tạo version mới cho các review kế tiếp |
| Reviews | `GET/POST /reviews`, `GET/PATCH/DELETE /reviews/{id}` | CRUD bản nháp cho paper chính và tập `reference_paper_ids` tùy chọn; sửa nhận xét thủ công; xóa mềm |
| Runs | `POST /reviews/{id}/runs`, `GET /runs/{id}`, `GET /runs/{id}/events`, `POST /runs/{id}/resume` | Bắt đầu tác vụ nền, theo dõi và tiếp tục run bị gián đoạn; không coi run là CRUD |
| Approval | `POST /reviews/{id}/approve` | Chốt bản review sau khi người dùng xem |
| Export | `GET /reviews/{id}/export.md` | Tải bản Paper Review đã duyệt dưới dạng Markdown; bản chưa duyệt trả 409 |

CRUD `POST` trả 201 và `Location`, `GET` trả 200, `PATCH` trả 200, `DELETE` trả 204, ID không có trả 404, dữ liệu không hợp lệ trả 422, trạng thái không cho phép thao tác trả 409. Danh sách có phân trang. Xóa mềm paper/rubric/review để giữ tính toàn vẹn của review và dẫn chứng đã tạo; tài nguyên đã xóa không xuất hiện trong danh sách mặc định. `POST /reviews/{id}/runs` trả **202 Accepted** cùng `run_id` và ID revision mới; một worker cục bộ xử lý nền, tối đa một run `running` trong MVP và các run khác ở trạng thái `queued`. Sau khi app khởi động lại, run đang chạy chuyển `interrupted`, giữ checkpoint, chỉ tiếp tục qua `POST /runs/{id}/resume` (202); không tự chạy lại. Resume lần hai hoặc resume run đã xong trả 409.

## 7. Harness và luồng agent

### Chuyển đổi và định vị nguồn

`DocumentIngress` là service xác định định dạng, kiểm tra tệp, gọi MarkItDown để tạo Markdown, tạo chunk và bản đồ vị trí nguồn. Với PDF, một bộ trích xuất theo trang chạy kèm để gắn `pdf_page` cho quote; với DOCX, bộ trích xuất theo đoạn/heading gắn `docx_paragraph`. **Không giả định Markdown từ MarkItDown tự giữ số trang:** bộ PDF mặc định có thể trả văn bản toàn tài liệu. Nếu không nối được một quote về vị trí gốc một cách rõ ràng, chunk được đánh dấu `unresolved_locator` và không dùng làm dẫn chứng `supported`. [Mã PDF converter của MarkItDown](https://github.com/microsoft/markitdown/blob/main/packages/markitdown/src/markitdown/converters/_pdf_converter.py).

### Hợp đồng harness tự xây

- `DocumentQueue`: đưa **toàn bộ paper chính** vào hàng đợi chunk/batch; lưu `processed_chunk_ids`, `remaining_chunk_ids`, hash và checkpoint để tiếp tục không xử lý trùng. Paper chính phải được bao phủ hết các chunk trong giới hạn đã công bố trước khi run là `completed`. Paper đối chiếu được đọc **theo claim liên quan**; với mỗi paper mà người dùng đã chọn, Comparator phải kiểm tra ít nhất một batch liên quan hoặc ghi rõ `not_assessed` cùng lý do. Report nêu các đoạn đã đọc và giới hạn so sánh, không tuyên bố đã đọc toàn bộ paper đối chiếu khi chưa làm vậy.
- `AgentRunner`: vòng lặp do nhóm viết, giới hạn mặc định 20 batch paper chính và 80 agent turns cho một run. Mỗi turn gửi trạng thái cho **Supervisor Agent**, nhận **đúng một** action có cấu trúc (`analyze`, `compare`, `verify`, `next_batch`, `finish`), kiểm tra điều kiện rồi gọi **chỉ worker được chọn**. Không khởi tạo phiên LLM và không gọi Groq cho worker còn lại trong turn đó; không chạy các worker song song. Kết quả worker và checkpoint quay về Supervisor để chọn turn tiếp theo. Nếu còn chunk paper chính chưa xử lý, paper đối chiếu được chọn chưa được đánh giá/ghi lý do, hoặc finding chưa được kiểm tra khi chạm giới hạn, run là `incomplete`, ghi rõ phần còn lại; không xuất report như đã bao phủ toàn bộ.
- `ToolRegistry` và `ToolGateway`: allowlist gồm `read_paper_chunks`, `read_reference_chunks`, `get_rubric`, `save_draft_finding`. Mỗi tool call được kiểm tra quyền, tham số và budget trước khi chạy. Không có shell, network search hoặc truy cập file tùy ý ở MVP.
- `PermissionPolicy`: đọc dữ liệu của paper chính, các paper đối chiếu đã chọn và rubric trong run được phép; ghi draft chỉ sau validation; approve luôn là hành động của người dùng; từ chối và ghi event khi tool ngoài allowlist hoặc ID ngoài run.
- `MemoryStore`: trạng thái run, chunk đã xử lý, finding đã chấp nhận và checkpoint. Không dùng ký ức xuyên người dùng trong MVP.
- `ContextBuilder`: chỉ đưa batch hiện hành, rubric, finding đã rút gọn và giới hạn token vào prompt; `paper_id`, `chunk_id` và locator luôn đi cùng văn bản.
- `OutputGate`: Pydantic/schema validation, giới hạn độ dài, kiểm tra source ID thuộc paper/version hiện hành hoặc tập đối chiếu đã chọn, kiểm tra quote xuất hiện trong chunk và locator còn truy xuất được. Nhận xét so sánh hai paper phải có dẫn chứng từ cả hai; finding không đạt quay lại tối đa một lần hoặc đánh dấu `needs_human_review`. OutputGate không tự gán `supported`: mọi finding mới/sửa phải qua Evidence Verifier trước khi có trạng thái đó.
- `RunEventRecorder`: lưu thứ tự batch, turn, agent được kích hoạt, lý do chọn/bỏ qua agent, action, tool, permission, checkpoint và kết quả validation cho dashboard; polling trước, SSE là mở rộng nếu cần.
- `VoiceProfile` (tùy chọn): `neutral`, `constructive`, `concise`; chỉ đổi cách diễn đạt sau khi finding đã qua output gate.
- `ApprovalPolicy`: `unsupported` không được xuất bản như finding có căn cứ; người dùng phải sửa/bỏ nó. `needs_human_review` có thể được giữ khi người dùng xác nhận thủ công, nhưng báo cáo vẫn hiển thị nhãn này và tên/ngày xác nhận; không tự nâng lên `supported`.

Hermes Agent là **tham khảo kiến trúc** cho vòng lặp turn → tool call → kết quả → turn tiếp theo, registry, budget và trace; code của dự án chỉ triển khai tập chức năng hẹp phục vụ review paper. [Hermes Agent Loop Internals](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/agent-loop.md).

### Bốn agent và luồng LangGraph

```text
MarkItDown + SourceLocator -> DocumentQueue -> Supervisor Agent
                                               |
                                      chọn một action / turn
                                               |
                         Scientific Review | Comparator | Verifier
                                  (chỉ worker được chọn chạy)
                                               |
                                         OutputGate + trace
                                               |
                            còn việc -> kết quả về Supervisor (loop)
                            đã đủ    -> Report Composer -> người dùng duyệt
```

**Supervisor Agent** kiểm soát tiến trình: chọn batch, gọi worker cần thiết, xem kết quả, yêu cầu bổ sung nguồn, quyết định dừng khi các mục bắt buộc đã đủ hoặc budget hết. **Scientific Review Agent** vừa trích xuất mục tiêu/phương pháp/kết quả/đóng góp được tuyên bố, vừa tạo nhận xét về điểm mạnh, phương pháp, hạn chế và chỗ thiếu bằng chứng. **Related-Work Comparator** chỉ so sánh với paper do người dùng chọn và nêu rõ giới hạn của tập đối chiếu. **Evidence Verifier** đối chiếu finding với source ID, quote và locator. Các agent dùng LangGraph cho state graph nội bộ; harness kiểm soát việc chuyển lượt, quyền tool và dừng vòng lặp. `Report Composer` là service xác định, không phải agent thứ năm. Nếu hết retry hoặc Groq lỗi kéo dài, run chuyển `failed` với mã lỗi; bản nháp và trace đã có vẫn xem được. API 429 được retry có giới hạn và tôn trọng `retry-after` nếu được cung cấp.

| Agent | Chỉ kích hoạt khi | Bỏ qua khi |
|---|---|---|
| Supervisor | Cần quyết định batch/worker tiếp theo hoặc dừng | Run đã dừng/chờ người dùng duyệt |
| Scientific Review | Batch của paper chính chưa được phân tích hoặc nhận xét cần sửa | Không còn nội dung/nhận xét cần xử lý |
| Related-Work Comparator | Người dùng đã chọn paper liên quan **và** còn claim/tiêu chí hoặc paper đối chiếu chưa được đánh giá | Không có nguồn đối chiếu hoặc mọi paper đã chọn đã được đánh giá/ghi lý do |
| Evidence Verifier | Có finding mới hoặc finding đã sửa cần kiểm tra | Không có finding chờ kiểm tra |

`AgentRunner` còn kiểm tra điều kiện kích hoạt độc lập với đề xuất của Supervisor. Nếu Supervisor chọn một worker không đủ điều kiện, harness ghi `agent_skipped` cùng lý do và yêu cầu Supervisor chọn lại trong budget. Điều này ngăn gọi LLM/tool không cần thiết và giúp inspector thể hiện chính xác agent nào đã hoạt động.

### Hợp đồng output

Mỗi finding có `criterion_code`, `kind`, `claim`, `evidence[]` (`paper_id`, `paper_chunk_id`, `locator_type`, `locator_value`, `quote`), `suggestion`, `verification_status` (`supported`, `needs_human_review`, `unsupported`). Report gồm các mục: tổng quan nghiên cứu, mục tiêu, phương pháp, kết quả, đóng góp được tuyên bố, điểm mạnh, hạn chế, chỗ thiếu bằng chứng, so sánh với **tập công trình do người dùng chọn** hoặc `not_assessed`, câu hỏi cho tác giả, giới hạn đánh giá và trạng thái duyệt. Cấu trúc hợp lệ và quote tồn tại không đồng nghĩa nhận xét đúng về mặt khoa học; UI luôn cho người dùng sửa/từ chối.

## 8. Giao diện và khả năng quan sát

1. **Library:** danh sách paper, upload PDF/DOCX và chỉnh metadata; trạng thái chuyển Markdown và định vị nguồn.
2. **Rubric editor:** CRUD rubric/criterion, version hiển thị rõ.
3. **Review workspace:** chọn paper chính, rubric và các paper đối chiếu tùy chọn trong thư viện; bắt đầu run, xem tiến độ.
4. **Harness inspector:** sơ đồ node/edge và timeline event; hiển thị batch/turn, chunk còn lại, context source IDs, tool call, permission allow/deny, validation pass/fail và output cuối. Có thể lọc theo agent/run.
5. **Draft review:** finding bên cạnh đoạn và vị trí nguồn (trang PDF hoặc đoạn DOCX); sửa, xóa, duyệt bản cuối; cảnh báo finding thiếu dẫn chứng. Bản đã duyệt có thể tải xuống dưới dạng Markdown; xuất PDF/DOCX là mở rộng sau MVP.

Dashboard dùng dữ liệu event thực, không vẽ tiến độ giả định. Không hiển thị chain-of-thought hoặc secret; hiển thị quyết định và bằng chứng có thể kiểm tra.

## 9. Giai đoạn 2: Literature Review nhiều paper

Chỉ bắt đầu phần này sau cổng ổn định ở M6. Thêm `ReviewProject`, `ProjectPaper`, `SynthesisDraft` và API CRUD tương ứng. Người dùng tạo câu hỏi nghiên cứu và chọn các paper đã tải lên; chức năng tự tìm trên Internet chưa thuộc bản đầu. Bản đầu của giai đoạn 2 dùng **thematic synthesis**: Supervisor điều phối cùng ba worker hiện có; Related-Work Comparator lấy các finding/chunk đã xác minh, lập nhóm chủ đề, bảng đồng thuận, mâu thuẫn, khoảng trống nghiên cứu và giới hạn của nguồn. Mỗi khẳng định phải trỏ tới ít nhất một paper/chunk; khẳng định so sánh phải trỏ tới các nguồn liên quan. Harness giữ nguyên giao diện loop/tool/memory/context/permission/output, chỉ bổ sung tool truy xuất theo project và policy kiểm tra paper thuộc project. Không âm thầm truy cập web hoặc tự thêm paper.

## 10. Roadmap và tiêu chí nghiệm thu

| Mốc | Sản phẩm | Kiểm chứng |
|---|---|---|
| M1: đặc tả | phạm vi, rubric mẫu, schema report | người dùng duyệt |
| M2: nền tảng | cấu trúc MVC, DB migration, OpenAPI, Dockerfile và Compose | `docker compose up --build -d` mở được FE/API; schema và status code đúng |
| M3: CRUD + ingestion | Paper/Rubric/Review + UI; MarkItDown PDF/DOCX + SourceLocator | test CRUD, xóa mềm, quote truy ngược trang PDF/đoạn DOCX |
| M4: harness | Supervisor loop, DocumentQueue, tool, memory, context, permission, trace | test budget, batch paper chính chưa xử lý, tham chiếu chưa đánh giá, run gián đoạn/resume, mỗi turn chỉ một worker, agent bị bỏ qua không gọi Groq, trace đúng thứ tự |
| M5: agent | bốn agent LangGraph + Groq + output gate | đủ mục Paper Review; Comparator chỉ chạy khi cần; Verifier chỉ chạy khi có finding; so sánh có quote và locator của hai phía; lỗi Groq không làm mất trace |
| M6: MVP ổn định | inspector, approval, export Markdown, tài liệu chạy Compose | demo end-to-end; `docker compose down/up` giữ SQLite/upload/checkpoint; pytest, Pylint và lint frontend đạt; không mất bản sửa khi chạy lại; không có finding `unsupported` trong report đã duyệt |
| M6E: đánh giá đề tài | bộ paper gắn nhãn, baseline LLM trực tiếp, bảng số liệu và báo cáo | so sánh trên cùng tập paper/rubric/model; công bố chỉ số và giới hạn; là kế hoạch thí nghiệm riêng sau khi MVP ổn định, trước M7 |
| M7: Literature Review | project nhiều paper + thematic synthesis | tổng hợp có nguồn từ các paper liên quan, CRUD project, test không trộn nguồn |
| M8: tìm kiếm tự động | sau Literature Review: đặc tả nguồn tìm kiếm, adapter, lọc trùng và bước người dùng chọn | không tự thêm paper; nguồn và lý do đề xuất kiểm tra được |

Trước mỗi mốc code, lập test cho hành vi có rủi ro. Có fixture PDF/DOCX mẫu và fake Groq client để test không cần chi phí API; một bài kiểm tra tích hợp Groq thật được chạy thủ công khi có key. Pylint và kiểm tra PEP 8 chạy trong CI/tập lệnh kiểm chứng, không chỉ ghi trong README.

### Chạy local bằng Docker Compose

**Cách chạy chính sau khi triển khai:** cài Docker Desktop với Compose, sao chép `.env.example` thành `.env`, chọn `DEMO_LLM_MODE=groq` và đặt `GROQ_API_KEY`, hoặc chọn `DEMO_LLM_MODE=fixture` để không cần API key. Từ thư mục `project03/`:

```powershell
docker compose up --build -d
docker compose exec backend python -m app.demo.seed
```

Sau đó mở giao diện `http://localhost:3000` và FastAPI docs `http://localhost:8000/docs`. `compose.yaml` có hai service: `frontend` (Next.js, cổng 3000) và `backend` (FastAPI cùng worker cục bộ, cổng 8000). Backend chạy migration trước khi nhận request, có healthcheck; seed demo phải chạy lặp lại an toàn. Compose đưa `DEMO_LLM_MODE` và `GROQ_API_KEY` từ `.env` vào **backend**. Container frontend liên lạc với backend qua tên service `backend`; trình duyệt trên máy dùng `localhost`. SQLite, PDF/DOCX tải lên, Markdown và checkpoint nằm trong named volume `app_data`, nên `docker compose down` rồi `docker compose up` không làm mất dữ liệu. Không dùng `docker compose down -v` khi muốn giữ dữ liệu. [Docker Compose networking](https://docs.docker.com/compose/how-tos/networking/), [volumes và `down`](https://docs.docker.com/reference/cli/docker/compose/down/).

```powershell
docker compose logs -f backend
docker compose down
```

Docker Compose là cách chạy demo local đã chọn; máy host chỉ cần Docker Desktop/Compose, không cần cài Python hoặc Node.js. `compose.yaml`, Dockerfile và `backend/docker/entrypoint.sh` là **hợp đồng cần xây ở M2–M6**, chưa chạy được khi mã nguồn chưa được tạo.

### Kịch bản trình bày MVP (mục tiêu 10–12 phút)

**Chuẩn bị:** một paper chính dạng PDF có lớp văn bản, một paper liên quan dạng DOCX và một rubric mẫu. `backend/app/demo/seed.py` chuẩn bị metadata/rubric; tệp mẫu có quyền sử dụng phù hợp và được lưu trong `demo_data/`. `.env.example` liệt kê biến cấu hình, key thật chỉ nằm trong `.env` cục bộ.

**Hai chế độ:** `DEMO_LLM_MODE=groq` dùng API thật; `DEMO_LLM_MODE=fixture` dùng phản hồi lưu sẵn cho cùng tài liệu mẫu. Chế độ fixture phục vụ demo dự phòng và test, phải gắn nhãn rõ trên UI; không trình bày nó như kết quả AI đang chạy thật. Cả hai đi qua cùng Supervisor loop, ToolGateway, OutputGate và event trace để vẫn chứng minh hành vi harness.

| Phút | Thao tác trình bày | Điều người xem kiểm chứng |
|---|---|---|
| 0–2 | Mở Library; tải PDF và DOCX, xem Markdown/locator | MarkItDown chuẩn hóa nội dung; PDF có trang, DOCX có đoạn nguồn |
| 2–3 | Mở Rubric, tạo/sửa một criterion | CRUD qua REST; thay đổi rubric có version |
| 3–5 | Chọn paper chính, DOCX liên quan và rubric; bấm Run | API tạo run 202, giao diện hiển thị trạng thái và tiến độ |
| 5–8 | Mở Harness Inspector trong lúc chạy | Supervisor chọn đúng một worker mỗi turn; thấy batch, tool, permission, memory/checkpoint và lý do agent bị bỏ qua |
| 8–10 | Mở Draft Review, bấm từng dẫn chứng | Claim truy về trang PDF/đoạn DOCX; so sánh có nguồn từ hai paper; finding thiếu nguồn bị đánh dấu |
| 10–12 | Sửa một finding, duyệt và tải Markdown | Người dùng kiểm soát bản cuối; bản xuất khớp bản đã duyệt |

**Demo kiểm soát output:** có một cấu hình fixture cố tình trả `paper_chunk_id` không thuộc run. OutputGate phải chặn, trace ghi `permission_denied` hoặc `validation_failed`, và report không gắn nhãn `supported` cho finding đó. Một run không chọn paper liên quan phải cho thấy Comparator được bỏ qua và không phát sinh lời gọi Groq của agent này. Nếu Groq thật trả 429, UI hiển thị retry có giới hạn hoặc trạng thái lỗi rõ ràng; người trình bày có thể chuyển sang fixture để tiếp tục.

## 11. Cách đánh giá đề tài

- **Câu hỏi nghiên cứu:** mô hình đa tác nhân với output gate có làm tăng tỷ lệ nhận xét có bằng chứng kiểm tra được so với một lời gọi LLM tạo report trực tiếp hay không? Khả năng quan sát của harness có giúp xác định nguyên nhân khi nhận xét bị từ chối không?
- **Bộ đánh giá:** chọn một tập paper PDF có lớp văn bản và DOCX thuộc lĩnh vực và giấy phép phù hợp; người đánh giá ghi nhãn một số nhận xét và vị trí dẫn chứng. Tách paper dùng để chỉnh prompt khỏi paper dùng để đánh giá.
- **Baseline:** cùng model Groq, cùng paper và rubric, một prompt đơn tạo report; không được truy cập thêm nguồn so với hệ đa tác nhân.
- **Chỉ số MVP:** tỷ lệ finding có quote và locator tồn tại thật; tỷ lệ dẫn chứng được người đánh giá chấp nhận là hỗ trợ claim; độ phủ các mục Paper Review report; tỷ lệ so sánh có nguồn ở cả hai paper; thời gian, số API call và token; mức hữu ích do người đánh giá chấm theo rubric. **Chỉ số Literature Review:** tỷ lệ nhận định tổng hợp có nguồn từ tập paper được chọn.
- **Kiểm tra harness:** bài test cố tình yêu cầu tool ngoài allowlist, source ID ngoài phạm vi, output sai schema, vượt max batch/turn, locator không phân giải được và Groq 429. Thêm test không chọn paper liên quan thì Comparator không nhận lời gọi Groq; không có finding mới thì Verifier không chạy; hai worker không chạy đồng thời. Đối chiếu event trace và trạng thái cuối với kết quả mong đợi.
- **Giới hạn nghiên cứu:** đánh giá của người đọc có yếu tố chủ quan; mẫu paper nhỏ không chứng minh hệ thống phù hợp mọi chuyên ngành; quote đúng vị trí chỉ là điều kiện cần cho độ đúng của nhận xét.

Số lượng paper và người đánh giá sẽ được khóa trong kế hoạch thí nghiệm sau khi biết nguồn dữ liệu và nguồn lực thực tế. Không báo cáo một chỉ số “accuracy” chung khi chưa định nghĩa nhãn và mẫu số.

M1–M6 là kế hoạch xây phần mềm MVP. M6E là phần đánh giá nghiên cứu bắt buộc để hoàn thiện đề tài, nhưng được lập thành kế hoạch thí nghiệm riêng sau khi phần mềm đủ ổn định; không làm chậm các mốc xây dựng MVP.

## 12. Phần còn để người triển khai quyết định

- Thư viện phụ trợ để định vị trang PDF và đoạn DOCX, migration và frontend component cụ thể sau một spike nhỏ về chất lượng chuyển đổi và đối chiếu quote.
- Model ID Groq theo khả năng và quota thực tế của tài khoản; kiểm tra tại lúc triển khai, không đóng cứng trong thiết kế.
- Giao diện đồ họa cuối cùng, miễn là có năm màn hình và các thông tin quan sát bắt buộc ở trên.

Các quyết định này không thay đổi hợp đồng API, quyền của harness hoặc ý nghĩa của hai giai đoạn.

Các lựa chọn cụ thể về demo một người dùng, kế hoạch triển khai đầu tiên chỉ đến M6, giới hạn mặc định 20 batch/80 agent turns, duyệt finding, lưu revision, đánh giá định tính và thematic synthesis là đề xuất của người thiết kế để khóa hành vi trước khi lập kế hoạch; người dùng có thể sửa khi duyệt tài liệu.
