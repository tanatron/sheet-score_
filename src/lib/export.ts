import * as XLSX from "xlsx";
import type { GradeResult } from "@/lib/api";

interface ExportRow {
  ไฟล์: string;
  รหัสวิชา: string;
  รหัสนักเรียน: string;
  คะแนน: number;
  คะแนนเต็ม: number;
  เปอร์เซ็นต์: number;
  [key: string]: string | number;
}

function buildRows(results: GradeResult[], fileNames: string[]): ExportRow[] {
  return results.map((r, i) => {
    const base: ExportRow = {
      ไฟล์: r.filename || fileNames[i] || `#${i + 1}`,
      รหัสวิชา: r.subject_code || "",
      รหัสนักเรียน: r.student_id || "",
      คะแนน: r.score ?? 0,
      คะแนนเต็ม: r.total ?? 0,
      "เปอร์เซ็นต์": r.percentage ?? 0,
    };
    if (r.details) {
      Object.entries(r.details).forEach(([q, d]) => {
        base[`ข้อ ${q} ตอบ`] = d.given;
        base[`ข้อ ${q} เฉลย`] = d.correct;
        base[`ข้อ ${q} ถูก`] = d.is_correct ? "✓" : "✗";
      });
    }
    return base;
  });
}

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function exportCSV(results: GradeResult[], fileNames: string[]) {
  const rows = buildRows(results, fileNames);
  const ws = XLSX.utils.json_to_sheet(rows);
  const csv = XLSX.utils.sheet_to_csv(ws);
  download(new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" }), "grading_results.csv");
}

export function exportExcel(results: GradeResult[], fileNames: string[]) {
  const rows = buildRows(results, fileNames);
  const ws = XLSX.utils.json_to_sheet(rows);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "ผลการตรวจ");
  const buf = XLSX.write(wb, { bookType: "xlsx", type: "array" });
  download(new Blob([buf], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }), "grading_results.xlsx");
}
