"use client";

import dynamic from "next/dynamic";

const NoteBlockEditor = dynamic(() => import("./NoteBlockEditor"), {
  ssr: false,
  loading: () => <div className="note-block-editor note-block-editor--loading" />,
});

export default NoteBlockEditor;
