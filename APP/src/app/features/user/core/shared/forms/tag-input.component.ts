import { DOCUMENT } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  NgZone,
  computed,
  forwardRef,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';
import { CdkConnectedOverlay, CdkOverlayOrigin, ConnectedPosition } from '@angular/cdk/overlay';
import { LucideAngularModule } from 'lucide-angular';

/** One suggestion in the type-ahead panel. `count` (how many records
 *  carry the tag) is shown dimmed on the right when present. */
export interface TagSuggestion {
  readonly value: string;
  readonly count?: number;
}

const PANEL_POSITIONS: ConnectedPosition[] = [
  { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 4 },
  { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -4 },
];
const MAX_VISIBLE_SUGGESTIONS = 8;
let nextId = 0;

/**
 * Chip-style tag input with type-ahead.
 *
 *   <crm-tag-input formControlName="tags" [suggestions]="opts" (lookup)="fetchTags($event)" />
 *
 * Value is `string[]` (ControlValueAccessor). Enter or comma adds the
 * typed text; text left in the box is added on blur. With `snapCase`,
 * a typed tag that matches a suggestion or an existing chip ignoring
 * case takes that spelling, so `hot` never forks an existing `Hot`.
 * `lookup` emits the typed text (and `''` on focus) so the parent can
 * fetch suggestions server-side; `added` / `removed` fire per chip for
 * parents that persist each change immediately.
 *
 * The suggestion panel renders in the CDK overlay container, so it is
 * never clipped by a scrolling modal body, and it follows the box when
 * any container scrolls.
 *
 * `appearance="inline"` is for record headers / side panels: chips and a
 * faint "+ Add tag" with no box until hovered or focused.
 */
@Component({
  selector: 'crm-tag-input',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CdkConnectedOverlay, CdkOverlayOrigin, LucideAngularModule],
  providers: [
    {
      provide: NG_VALUE_ACCESSOR,
      useExisting: forwardRef(() => TagInputComponent),
      multi: true,
    },
  ],
  template: `
    <label
      cdkOverlayOrigin
      #origin="cdkOverlayOrigin"
      [for]="inputId"
      class="flex w-full cursor-text flex-wrap items-center gap-1.5 border transition focus-within:border-accent focus-within:ring-1 focus-within:ring-accent"
      [class.border-subtle]="!inline()"
      [class.bg-app]="!inline()"
      [class.hover:border-faint]="!inline()"
      [class.border-transparent]="inline()"
      [class.hover:bg-surface-2]="inline()"
      [class.focus-within:bg-app]="inline()"
      [class.min-h-[40px]]="!dense()"
      [class.rounded-[9px]]="!dense()"
      [class.px-2]="!dense()"
      [class.py-1.5]="!dense()"
      [class.min-h-[32px]]="dense()"
      [class.rounded-md]="dense()"
      [class.px-1.5]="dense()"
      [class.py-1]="dense()"
      [class.opacity-50]="disabled()"
      [class.pointer-events-none]="disabled()"
    >
      @for (tag of tags(); track tag) {
        <span
          class="inline-flex h-6 max-w-full items-center gap-0.5 rounded-full bg-accent-soft pl-2.5 pr-1 text-[12px] font-medium text-accent"
        >
          <span class="truncate">{{ tag }}</span>
          <button
            type="button"
            class="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full hover:bg-accent/15"
            [attr.aria-label]="'Remove tag ' + tag"
            (click)="removeTag(tag); $event.stopPropagation()"
          >
            <lucide-icon name="x" class="h-3 w-3" />
          </button>
        </span>
      }
      @if (inline() && !disabled()) {
        <lucide-icon name="plus" class="-mr-1 ml-0.5 h-3.5 w-3.5 shrink-0 text-faint" />
      }
      <input
        #textInput
        type="text"
        [id]="inputId"
        role="combobox"
        autocomplete="off"
        class="flex-1 border-0 bg-transparent px-1 py-0.5 text-[13px] text-default placeholder:text-faint focus:outline-none focus:ring-0"
        [class.min-w-[7rem]]="!inline()"
        [class.min-w-[5.5rem]]="inline()"
        [attr.aria-label]="ariaLabel()"
        [attr.aria-expanded]="panelOpen()"
        [attr.aria-controls]="listboxId"
        aria-autocomplete="list"
        [placeholder]="inline() || tags().length === 0 ? placeholder() : ''"
        [value]="text()"
        [disabled]="disabled()"
        (input)="onInput($event)"
        (keydown)="onKeydown($event)"
        (focus)="onFocus()"
        (blur)="onBlur()"
      />
    </label>
    @if (message(); as msg) {
      <p class="field-error mt-1">{{ msg }}</p>
    }

    <ng-template
      cdkConnectedOverlay
      [cdkConnectedOverlayOrigin]="origin"
      [cdkConnectedOverlayOpen]="panelOpen()"
      [cdkConnectedOverlayPositions]="positions"
      [cdkConnectedOverlayWidth]="panelWidth()"
      (overlayOutsideClick)="onOutsideClick($event)"
      (detach)="closePanel()"
    >
      <div
        [id]="listboxId"
        class="max-h-60 w-full overflow-y-auto rounded-md border border-subtle bg-surface p-1 shadow-lg"
        role="listbox"
      >
        @for (s of visibleSuggestions(); track s.value; let i = $index) {
          <button
            type="button"
            role="option"
            class="flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-xs text-default transition hover:bg-surface-2"
            [class.bg-surface-2]="i === activeIndex()"
            [attr.aria-selected]="i === activeIndex()"
            (mousedown)="$event.preventDefault()"
            (click)="addTag(s.value)"
          >
            <span class="truncate">{{ s.value }}</span>
            @if (s.count !== undefined) {
              <span class="ml-2 shrink-0 font-mono text-[10px] text-faint">{{ s.count }}</span>
            }
          </button>
        }
        @if (createLabel(); as label) {
          <button
            type="button"
            class="flex w-full items-center gap-1.5 rounded px-2 py-1.5 text-left text-xs text-muted transition hover:bg-surface-2"
            [class.bg-surface-2]="activeIndex() === visibleSuggestions().length"
            (mousedown)="$event.preventDefault()"
            (click)="commitText()"
          >
            <lucide-icon name="plus" class="h-3 w-3 shrink-0" />
            <span class="truncate"
              >Add <span class="font-medium text-default">{{ label }}</span></span
            >
          </button>
        }
      </div>
    </ng-template>
  `,
})
export class TagInputComponent implements ControlValueAccessor {
  readonly suggestions = input<ReadonlyArray<TagSuggestion>>([]);
  readonly maxTags = input(32);
  readonly maxLength = input(64);
  /** Reuse an existing spelling when the typed tag matches it ignoring case. */
  readonly snapCase = input(true);
  readonly placeholder = input('Add a tag…');
  readonly ariaLabel = input<string | null>('Tags');
  /** Compact 32px variant for inline editors; default matches `.input`. */
  readonly dense = input(false);
  /** `field` is a form input; `inline` shows no box until hovered / focused. */
  readonly appearance = input<'field' | 'inline'>('field');

  readonly lookup = output<string>();
  readonly added = output<string>();
  readonly removed = output<string>();

  protected readonly inline = computed(() => this.appearance() === 'inline');
  protected readonly tags = signal<string[]>([]);
  protected readonly text = signal('');
  protected readonly message = signal<string | null>(null);
  protected readonly disabled = signal(false);
  protected readonly focused = signal(false);
  protected readonly activeIndex = signal(-1);
  protected readonly panelWidth = signal(0);
  protected readonly positions = PANEL_POSITIONS;
  protected readonly inputId = `crm-tag-input-${nextId}`;
  protected readonly listboxId = `crm-tag-input-${nextId++}-listbox`;

  private readonly origin = viewChild.required<CdkOverlayOrigin>('origin');
  private readonly textInput = viewChild.required<ElementRef<HTMLInputElement>>('textInput');
  private readonly overlay = viewChild(CdkConnectedOverlay);

  protected readonly visibleSuggestions = computed<TagSuggestion[]>(() => {
    const chosen = new Set(this.tags().map((t) => t.toLowerCase()));
    const q = this.text().trim().toLowerCase();
    return this.suggestions()
      .filter((s) => !chosen.has(s.value.toLowerCase()))
      .filter((s) => !q || s.value.toLowerCase().includes(q))
      .slice(0, MAX_VISIBLE_SUGGESTIONS);
  });

  /** "Add <text>" row — only when the text is not already an exact
   *  (case-insensitive) suggestion or chip. */
  protected readonly createLabel = computed<string | null>(() => {
    const value = this.normalise(this.text());
    if (!value) return null;
    const lower = value.toLowerCase();
    const known =
      this.suggestions().some((s) => s.value.toLowerCase() === lower) ||
      this.tags().some((t) => t.toLowerCase() === lower);
    return known ? null : value;
  });

  protected readonly panelOpen = computed(
    () =>
      this.focused() &&
      !this.disabled() &&
      (this.visibleSuggestions().length > 0 || this.createLabel() !== null),
  );

  private onChangeFn: (value: string[]) => void = () => undefined;
  private onTouchedFn: () => void = () => undefined;

  constructor() {
    // Pages scroll inside containers the CDK doesn't watch (the app
    // shell's main area, modal bodies), which left the open panel behind
    // while the box moved. Follow every scroll — capture phase, because
    // scroll events don't bubble.
    const doc = inject(DOCUMENT);
    const follow = (): void => {
      if (this.panelOpen()) this.overlay()?.overlayRef?.updatePosition();
    };
    inject(NgZone).runOutsideAngular(() =>
      doc.addEventListener('scroll', follow, { capture: true, passive: true }),
    );
    inject(DestroyRef).onDestroy(() =>
      doc.removeEventListener('scroll', follow, { capture: true }),
    );
  }

  // --- ControlValueAccessor ------------------------------------------
  writeValue(value: string[] | null | undefined): void {
    this.tags.set([...(value ?? [])]);
    this.message.set(null);
  }

  registerOnChange(fn: (value: string[]) => void): void {
    this.onChangeFn = fn;
  }

  registerOnTouched(fn: () => void): void {
    this.onTouchedFn = fn;
  }

  setDisabledState(isDisabled: boolean): void {
    this.disabled.set(isDisabled);
  }
  // -------------------------------------------------------------------

  protected onFocus(): void {
    this.panelWidth.set(this.origin().elementRef.nativeElement.getBoundingClientRect().width);
    this.focused.set(true);
    this.lookup.emit(this.text().trim());
  }

  protected onBlur(): void {
    this.commitText();
    this.focused.set(false);
    this.activeIndex.set(-1);
    this.onTouchedFn();
  }

  protected onInput(event: Event): void {
    const raw = (event.target as HTMLInputElement).value;
    // Typing or pasting a comma commits everything before it.
    if (raw.includes(',')) {
      const parts = raw.split(',');
      const rest = parts.pop() ?? '';
      parts.forEach((part) => this.addTag(part));
      this.setText(rest);
    } else {
      this.setText(raw);
    }
    this.message.set(null);
    this.focused.set(true);
    this.activeIndex.set(-1);
    this.lookup.emit(this.text().trim());
  }

  protected onKeydown(event: KeyboardEvent): void {
    const optionCount = this.visibleSuggestions().length + (this.createLabel() ? 1 : 0);
    switch (event.key) {
      case 'Enter': {
        event.preventDefault();
        const i = this.activeIndex();
        const picked = i >= 0 ? this.visibleSuggestions()[i] : undefined;
        if (picked) this.addTag(picked.value);
        else this.commitText();
        break;
      }
      case 'ArrowDown':
        if (optionCount > 0) {
          event.preventDefault();
          this.activeIndex.set((this.activeIndex() + 1) % optionCount);
        }
        break;
      case 'ArrowUp':
        if (optionCount > 0) {
          event.preventDefault();
          this.activeIndex.set(this.activeIndex() <= 0 ? optionCount - 1 : this.activeIndex() - 1);
        }
        break;
      case 'Backspace':
        if (this.text() === '' && this.tags().length > 0) {
          this.removeTag(this.tags()[this.tags().length - 1]);
        }
        break;
      case 'Escape':
        if (this.panelOpen()) {
          event.stopPropagation();
          this.closePanel();
        }
        break;
    }
  }

  protected closePanel(): void {
    this.focused.set(false);
    this.activeIndex.set(-1);
  }

  /** The text box sits outside the overlay, so clicks on it must not
   *  count as "outside". */
  protected onOutsideClick(event: MouseEvent): void {
    const target = event.target;
    if (target instanceof Node && this.origin().elementRef.nativeElement.contains(target)) return;
    this.closePanel();
  }

  /** Add whatever is typed in the box (Enter, comma, blur, "Add" row).
   *  Text that fails validation stays in the box next to the message. */
  protected commitText(): void {
    if (!this.normalise(this.text()) || this.addTag(this.text())) this.setText('');
  }

  /** Returns false when the tag was refused (message shown). */
  protected addTag(raw: string): boolean {
    const value = this.normalise(raw);
    if (!value) return true;
    if (value.length > this.maxLength()) {
      this.message.set(`Tags can be at most ${this.maxLength()} characters.`);
      return false;
    }
    const lower = value.toLowerCase();
    if (this.tags().some((t) => t === value || (this.snapCase() && t.toLowerCase() === lower))) {
      this.setText('');
      return true;
    }
    if (this.tags().length >= this.maxTags()) {
      this.message.set(`You can add at most ${this.maxTags()} tags.`);
      return false;
    }
    const snapped = this.snapCase()
      ? (this.suggestions().find((s) => s.value.toLowerCase() === lower)?.value ?? value)
      : value;
    this.tags.set([...this.tags(), snapped]);
    this.setText('');
    this.message.set(null);
    this.activeIndex.set(-1);
    this.onChangeFn(this.tags());
    this.added.emit(snapped);
    return true;
  }

  protected removeTag(tag: string): void {
    if (this.disabled()) return;
    this.tags.set(this.tags().filter((t) => t !== tag));
    this.message.set(null);
    this.onChangeFn(this.tags());
    this.removed.emit(tag);
  }

  private setText(value: string): void {
    this.text.set(value);
    // Keep the DOM in step when the text is cleared programmatically
    // (the `[value]` binding alone does not reset a field the user typed in).
    const el = this.textInput().nativeElement;
    if (el.value !== value) el.value = value;
  }

  private normalise(raw: string): string {
    return raw.normalize('NFC').trim();
  }
}
