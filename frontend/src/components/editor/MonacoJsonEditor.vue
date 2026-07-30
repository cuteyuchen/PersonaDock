<script setup lang="ts">
import * as monaco from 'monaco-editor'
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import JsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = withDefaults(defineProps<{ modelValue: string; readOnly?: boolean; height?: string }>(), { readOnly: false, height: '560px' })
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const host = ref<HTMLElement | null>(null)
let editor: monaco.editor.IStandaloneCodeEditor | null = null
let internal = false

;(self as unknown as { MonacoEnvironment: { getWorker: (_moduleId: string, label: string) => Worker } }).MonacoEnvironment = {
  getWorker(_moduleId: string, label: string) {
    return label === 'json' ? new JsonWorker() : new EditorWorker()
  },
}

onMounted(() => {
  if (!host.value) return
  editor = monaco.editor.create(host.value, {
    value: props.modelValue,
    language: 'json',
    readOnly: props.readOnly,
    automaticLayout: true,
    minimap: { enabled: false },
    fontSize: 12,
    lineHeight: 19,
    tabSize: 2,
    insertSpaces: true,
    wordWrap: 'on',
    scrollBeyondLastLine: false,
    renderLineHighlight: 'line',
    bracketPairColorization: { enabled: true },
    padding: { top: 10, bottom: 10 },
  })
  editor.onDidChangeModelContent(() => {
    if (internal || !editor) return
    emit('update:modelValue', editor.getValue())
  })
})

watch(() => props.modelValue, (value) => {
  if (!editor || editor.getValue() === value) return
  internal = true
  editor.setValue(value)
  internal = false
})
watch(() => props.readOnly, (value) => editor?.updateOptions({ readOnly: value }))
onBeforeUnmount(() => editor?.dispose())
</script>

<template><div ref="host" class="overflow-hidden rounded-md border bg-[#1e1e1e]" :style="{ height }" /></template>
