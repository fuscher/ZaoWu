<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from '@/i18n'

const { t } = useI18n()

const display = ref('0')
const previousValue = ref<number | null>(null)
const operation = ref<string | null>(null)
const resetNext = ref(false)
const expression = ref('')
const error = ref(false)

const displayFormatted = computed(() => {
  const num = parseFloat(display.value)
  if (Number.isInteger(num) && Math.abs(num) < 1e15) {
    return num.toString()
  }
  if (Math.abs(num) > 1e15 || (Math.abs(num) < 1e-10 && num !== 0)) {
    return num.toExponential(6)
  }
  return display.value
})

function appendNumber(num: string) {
  resetFromError()
  if (resetNext.value) {
    display.value = num
    resetNext.value = false
  } else {
    if (num === '.' && display.value.includes('.')) return
    if (display.value === '0' && num !== '.') {
      display.value = num
    } else {
      display.value += num
    }
  }
}

function setOperation(op: string) {
  resetFromError()
  const current = parseFloat(display.value)
  if (operation.value && !resetNext.value) {
    calculate()
  }
  previousValue.value = current
  operation.value = op
  resetNext.value = true
  expression.value = `${current} ${op}`
}

function calculate() {
  const current = parseFloat(display.value)
  const prev = previousValue.value
  if (prev === null || !operation.value) return

  let result: number
  switch (operation.value) {
    case '+': result = prev + current; break
    case '−': result = prev - current; break
    case '×': result = prev * current; break
    case '÷': result = current === 0 ? NaN : prev / current; break
    default: return
  }

  if (!isFinite(result)) {
    display.value = t('calculator.error')
    error.value = true
    resetNext.value = true
    previousValue.value = null
    operation.value = null
    expression.value = ''
    return
  }

  display.value = result.toString()
  previousValue.value = null
  operation.value = null
  expression.value = `= ${result}`
  resetNext.value = true
}

function resetFromError() {
  if (error.value) {
    clearAll()
  }
}

function clearAll() {
  display.value = '0'
  previousValue.value = null
  operation.value = null
  resetNext.value = false
  expression.value = ''
  error.value = false
}

function negate() {
  resetFromError()
  display.value = (parseFloat(display.value) * -1).toString()
}

function percent() {
  resetFromError()
  display.value = (parseFloat(display.value) / 100).toString()
}

function backspace() {
  if (error.value || resetNext.value) return
  display.value = display.value.length > 1 ? display.value.slice(0, -1) : '0'
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key >= '0' && e.key <= '9') appendNumber(e.key)
  else if (e.key === '.') appendNumber('.')
  else if (e.key === '+') setOperation('+')
  else if (e.key === '-') setOperation('−')
  else if (e.key === '*') setOperation('×')
  else if (e.key === '/') { e.preventDefault(); setOperation('÷') }
  else if (e.key === 'Enter' || e.key === '=') calculate()
  else if (e.key === 'Escape') clearAll()
  else if (e.key === 'Backspace') backspace()
  else if (e.key === '%') percent()
}
</script>

<template>
  <div class="calculator" tabindex="0" @keydown="handleKeydown">
    <div class="expression">{{ expression }}</div>
    <div class="display" :class="{ error: display === t('calculator.error') }">{{ error ? t('calculator.error') : displayFormatted }}</div>
    <div class="buttons">
      <button class="btn function" @click="clearAll">{{ t('calculator.ac') }}</button>
      <button class="btn function" @click="negate">±</button>
      <button class="btn function" @click="percent">%</button>
      <button class="btn operator" @click="setOperation('÷')">÷</button>

      <button class="btn number" @click="appendNumber('7')">7</button>
      <button class="btn number" @click="appendNumber('8')">8</button>
      <button class="btn number" @click="appendNumber('9')">9</button>
      <button class="btn operator" @click="setOperation('×')">×</button>

      <button class="btn number" @click="appendNumber('4')">4</button>
      <button class="btn number" @click="appendNumber('5')">5</button>
      <button class="btn number" @click="appendNumber('6')">6</button>
      <button class="btn operator" @click="setOperation('−')">−</button>

      <button class="btn number" @click="appendNumber('1')">1</button>
      <button class="btn number" @click="appendNumber('2')">2</button>
      <button class="btn number" @click="appendNumber('3')">3</button>
      <button class="btn operator" @click="setOperation('+')">+</button>

      <button class="btn number zero" @click="appendNumber('0')">0</button>
      <button class="btn number" @click="appendNumber('.')">.</button>
      <button class="btn operator equals" @click="calculate">=</button>
    </div>
  </div>
</template>

<style scoped>
.calculator {
  width: 320px;
  background: #1c1c1e;
  border-radius: 16px;
  padding: 20px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  outline: none;
  user-select: none;
}

.expression {
  text-align: right;
  color: #8e8e93;
  font-size: 16px;
  min-height: 24px;
  padding: 0 8px;
  word-break: break-all;
}

.display {
  text-align: right;
  color: #fff;
  font-size: 48px;
  font-weight: 300;
  padding: 8px 8px 16px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.display.error {
  font-size: 32px;
  color: #ff453a;
}

.buttons {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.btn {
  height: 64px;
  border: none;
  border-radius: 32px;
  font-size: 24px;
  cursor: pointer;
  transition: filter 0.1s;
  outline: none;
}

.btn:active {
  filter: brightness(1.4);
}

.btn.number {
  background: #2c2c2e;
  color: #fff;
}

.btn.number.zero {
  grid-column: span 2;
}

.btn.function {
  background: #636366;
  color: #fff;
}

.btn.operator {
  background: #ff9f0a;
  color: #fff;
}

.btn.operator.equals {
  background: #ff9f0a;
}
</style>
