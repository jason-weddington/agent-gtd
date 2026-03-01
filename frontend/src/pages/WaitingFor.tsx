import GtdItemList from '../components/GtdItemList'

export default function WaitingFor() {
  return (
    <GtdItemList
      title="Waiting For"
      statusFilter="waiting_for"
      emptyTitle="Nothing waiting"
      emptyDescription="Items triaged as Waiting For will appear here."
      showWaitingOn
    />
  )
}
