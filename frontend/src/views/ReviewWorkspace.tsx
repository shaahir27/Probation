import { QueueDigest, QueueGroup, QueueItem } from "../api/types";
import { ReviewDecision } from "../components/queue/ReviewForm";
import { QueueGate } from "../navigation";
import { ItemDetailView } from "./ItemDetailView";
import { QueueView } from "./QueueView";

interface ReviewWorkspaceProps {
  items: QueueItem[];
  digests: QueueDigest[];
  handledCount: number;
  handledDigests: QueueGroup[];
  expiredCount: number;
  expiredDigests: QueueGroup[];
  gate: QueueGate;
  onGateChange(gate: QueueGate): void;
  selectedId: string | null;
  selectedItem?: QueueItem;
  authenticated: boolean;
  review: {
    busy: boolean;
    conflict: string | null;
    error: string | null;
    submit(proposalId: string, decision: ReviewDecision): Promise<string | null>;
    refresh(): void;
  };
  onSelect(item: QueueItem): void;
  onBack(): void;
}

export function ReviewWorkspace(props: ReviewWorkspaceProps) {
  const {
    items,
    digests,
    handledCount,
    handledDigests,
    expiredCount,
    expiredDigests,
    gate,
    onGateChange,
    selectedId,
    selectedItem,
    authenticated,
    review,
    onSelect,
    onBack,
  } = props;
  return <div className={`review-split ${selectedId ? "has-selection" : "no-selection"}`} data-ui="review-workspace">
    <div className="review-list-pane">
      <QueueView
        items={items}
        digests={digests}
        handledCount={handledCount}
        handledDigests={handledDigests}
        expiredCount={expiredCount}
        expiredDigests={expiredDigests}
        gate={gate}
        onGateChange={onGateChange}
        onSelectItem={onSelect}
        selectedId={selectedId}
      />
    </div>
    <div className="review-detail-pane">
      {selectedId && (
        <ItemDetailView
          id={selectedId}
          item={selectedItem}
          authenticated={authenticated}
          review={review}
          onBack={onBack}
        />
      )}
    </div>
  </div>;
}
