import { useEffect, useRef } from 'react'
import { useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { Markdown } from '@tiptap/markdown'
import TaskList from '@tiptap/extension-task-list'
import TaskItem from '@tiptap/extension-task-item'
import Link from '@tiptap/extension-link'
import Placeholder from '@tiptap/extension-placeholder'
import {
  LinkBubbleMenuHandler,
  LinkBubbleMenu,
  RichTextEditorProvider,
  RichTextField,
  MenuControlsContainer,
  MenuSelectHeading,
  MenuDivider,
  MenuButtonBold,
  MenuButtonItalic,
  MenuButtonStrikethrough,
  MenuButtonEditLink,
  MenuButtonBulletedList,
  MenuButtonOrderedList,
  MenuButtonTaskList,
  MenuButtonBlockquote,
  MenuButtonCode,
  MenuButtonCodeBlock,
  MenuButtonHorizontalRule,
  MenuButtonUndo,
  MenuButtonRedo,
} from 'mui-tiptap'

interface NoteEditorProps {
  content: string
  onChange: (markdown: string) => void
}

export default function NoteEditor({ content, onChange }: NoteEditorProps) {
  const onChangeRef = useRef(onChange)
  useEffect(() => {
    onChangeRef.current = onChange
  }, [onChange])

  const editor = useEditor({
    extensions: [
      StarterKit,
      Markdown,
      TaskList,
      TaskItem.configure({ nested: true }),
      Link.configure({ openOnClick: false }),
      LinkBubbleMenuHandler,
      Placeholder.configure({ placeholder: 'Start writing...' }),
    ],
    content,
    contentType: 'markdown',
    immediatelyRender: false,
    shouldRerenderOnTransaction: false,
    onUpdate: ({ editor: ed }) => {
      onChangeRef.current(ed.getMarkdown())
    },
  })

  // Sync content prop when it changes (e.g. switching between notes)
  const prevContentRef = useRef(content)
  useEffect(() => {
    if (editor && content !== prevContentRef.current) {
      prevContentRef.current = content
      editor.commands.setContent(content, { emitUpdate: false, contentType: 'markdown' })
    }
  }, [editor, content])

  return (
    <RichTextEditorProvider editor={editor}>
      <RichTextField
        controls={
          <MenuControlsContainer>
            <MenuSelectHeading />
            <MenuDivider />
            <MenuButtonBold />
            <MenuButtonItalic />
            <MenuButtonStrikethrough />
            <MenuDivider />
            <MenuButtonEditLink />
            <MenuDivider />
            <MenuButtonBulletedList />
            <MenuButtonOrderedList />
            <MenuButtonTaskList />
            <MenuDivider />
            <MenuButtonBlockquote />
            <MenuButtonCode />
            <MenuButtonCodeBlock />
            <MenuButtonHorizontalRule />
            <MenuDivider />
            <MenuButtonUndo />
            <MenuButtonRedo />
          </MenuControlsContainer>
        }
      />
      <LinkBubbleMenu />
    </RichTextEditorProvider>
  )
}
