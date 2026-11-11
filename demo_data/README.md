# Bộ paper và rubric dùng thử

Bộ này thay thế các tài liệu giả lập cũ, được xuất từ thư viện local ngày 11/11/2026.

- `13685-33601-1-PB.pdf`: Nghiên cứu ứng dụng công cụ trí tuệ nhân tạo trong hỗ trợ người nước ngoài học tiếng Việt (9 trang). Nguồn: https://jst.tnu.edu.vn/jst/article/viewFile/13685/pdf
- `ijli-3-2-5.pdf`: ChatGPT in Language Learning: Perspectives from Vietnamese Students in Vietnam and the USA (14 trang). Nguồn: https://doi.org/10.54855/ijli.24325
- `library.json`: giữ tiêu đề và metadata đang dùng trên máy, cấu hình paper chính/paper đối chiếu, cùng rubric **Review bài báo AI tiếng Việt** với 6 tiêu chí và hướng dẫn gốc theo thứ tự.

Backend tự nhập bộ này khi khởi động với database trống. Không tự chạy review hoặc gọi Groq. Lệnh nhập thủ công: `docker compose exec -T backend python -m app.demo.seed`.

Rubric được tạo thành version 1 trên máy mới, với nội dung từ version 2 đang dùng trên máy nguồn. ID và lịch sử chỉnh sửa cũ không được sao chép.

Các paper thuộc tác giả và nhà xuất bản tương ứng; giấy phép mã nguồn của dự án không áp dụng cho nội dung bài báo. Thư mục này không chứa database, bản review, log hoặc API key.
