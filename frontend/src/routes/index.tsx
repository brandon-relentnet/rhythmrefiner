import { createFileRoute } from '@tanstack/react-router'
import { useMutation } from '@tanstack/react-query'
import { Bar } from 'react-chartjs-2'
import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  Tooltip,
} from 'chart.js'
import { Fragment, useMemo, useState } from 'react'
import type { FormEvent } from 'react'

export interface Track {
  name: string
  url: string
  order: number
}

export interface ArtistSummary {
  name: string
  url: string
  count: number
  share: number
  tracks: Array<Track>
}

export interface PlaylistSummary {
  totalTracks: number
  uniqueArtists: number
  artists: Array<ArtistSummary>
}

interface RecommendationTrack {
  id: string
  name: string
  url: string
  artistId: string
  artistName: string
  artistUrl: string
  confidencePct: number
  scores: {
    artistScore: number
    artistCount: number
    artistShare: number
    rankScore: number
    genreScore: number
    popularityScore: number
    balancePenalty: number
    rawScore: number
    finalScore: number
    confidencePct: number
  }
}

interface RecommendationResponse {
  recommendedTracks: Array<RecommendationTrack>
  totalTracks: number
  playlistGenreProfile: Record<string, number> | null
  weights: Record<string, number>
}

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip, Legend)

export const Route = createFileRoute('/')({
  component: App,
})

const fetchPlaylistSummary = async (playlistUrl: string) => {
  const res = await fetch('http://localhost:8000/api/playlist-summary', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ playlistUrl }),
  })

  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}))
    throw new Error(errBody.detail || `Request failed with ${res.status}`)
  }

  return (await res.json()) as PlaylistSummary
}

interface RecommendationsRequestBody {
  playlistUrl: string
  maxArtistCount: number | null
}

const fetchRecommendations = async (body: RecommendationsRequestBody) => {
  const res = await fetch('http://localhost:8000/api/recommendations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}))
    throw new Error(errBody.detail || `Request failed with ${res.status}`)
  }

  return (await res.json()) as RecommendationResponse
}

function App() {
  const [playlistUrl, setPlaylistUrl] = useState('')
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [showRecs, setShowRecs] = useState(false)
  const [recMode, setRecMode] = useState<'popular' | 'lesser'>('popular')

  const playlistQuery = useMutation<PlaylistSummary, Error, string>({
    mutationFn: fetchPlaylistSummary,
  })

  const recommendationsQuery = useMutation<
    RecommendationResponse,
    Error,
    RecommendationsRequestBody
  >({
    mutationFn: fetchRecommendations,
  })

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!playlistUrl.trim()) return

    setExpanded({})
    playlistQuery.reset()
    recommendationsQuery.reset()
    setShowRecs(false)
    setRecMode('popular')
    playlistQuery.mutate(playlistUrl.trim())
  }

  const toggleArtist = (id: string) => {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  const data = playlistQuery.data
  const error = playlistQuery.error
  const loading = playlistQuery.isPending
  const recs = recommendationsQuery.data
  const recsError = recommendationsQuery.error
  const recsLoading = recommendationsQuery.isPending

  const topArtists: Array<ArtistSummary> = data?.artists.slice(0, 20) ?? []

  const artistCountsByName = useMemo(() => {
    if (!data?.artists) return {}
    return data.artists.reduce<Record<string, number>>((acc, artist) => {
      acc[artist.name.toLowerCase()] = artist.count
      return acc
    }, {})
  }, [data?.artists])

  const derivedMaxArtistCount = useMemo(() => {
    if (recMode !== 'lesser') return null
    const artists = data?.artists ?? []
    if (artists.length === 0) return 1
    const counts = [...artists.map((a) => a.count)].sort((a, b) => a - b)
    const medianIdx = Math.floor(counts.length / 2)
    return Math.max(1, counts[medianIdx])
  }, [recMode, data?.artists])

  const requestRecommendations = () => {
    if (!playlistUrl.trim()) return
    setShowRecs(true)
    recommendationsQuery.mutate({
      playlistUrl: playlistUrl.trim(),
      maxArtistCount: derivedMaxArtistCount,
    })
  }

  const filteredTracks =
    recs?.recommendedTracks &&
    recMode === 'lesser' &&
    derivedMaxArtistCount != null
      ? recs.recommendedTracks.filter((track) => {
          const key = track.artistName.toLowerCase()
          const playlistCount = artistCountsByName[key] ?? 0
          return playlistCount <= derivedMaxArtistCount
        })
      : (recs?.recommendedTracks ?? [])

  const chartData = {
    labels: topArtists.map((a) => a.name),
    datasets: [
      {
        label: 'Track count',
        data: topArtists.map((a) => a.count),
        backgroundColor: 'oklch(0.765 0.177 163.223)',
        borderColor: '#10b981',
        hoverBackgroundColor: 'oklch(1.765 0.177 163.223)',
      },
    ],
  }

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false as const,
    scales: {
      y: {
        beginAtZero: true,
        ticks: { precision: 0 },
      },
    },
    plugins: {
      legend: { display: false },
    },
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6 md:p-10">
      <div className="max-w-6xl mx-auto space-y-6">
        <header className="space-y-2">
          <h1 className="text-3xl font-semibold tracking-tight">
            Spotify Playlist Artist Breakdown
          </h1>
          <p className="text-sm text-slate-300">
            Paste a Spotify playlist URL and get per-artist counts, songs, and a
            top-20 chart.
          </p>
        </header>

        <form
          onSubmit={handleSubmit}
          className="flex flex-col sm:flex-row gap-3"
        >
          <input
            type="text"
            className="flex-1 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            placeholder="https://open.spotify.com/playlist/..."
            value={playlistUrl}
            onChange={(e) => setPlaylistUrl(e.target.value)}
          />
          <button
            type="submit"
            disabled={loading}
            className="rounded-md bg-emerald-500 px-4 py-2 text-sm font-medium text-slate-900 hover:bg-emerald-400 disabled:opacity-60 shadow-sm shadow-emerald-900/50"
          >
            {loading ? 'Analyzing…' : 'Analyze'}
          </button>
        </form>

        {error && <div className="text-sm text-red-400">{error.message}</div>}

        {data && (
          <div className="grid gap-6 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] items-start">
            {/* Table */}
            <div className="space-y-3">
              <div className="flex flex-wrap gap-3 items-center text-xs text-slate-300">
                <span>
                  <span className="font-semibold text-slate-100">
                    Total tracks:{' '}
                  </span>
                  {data.totalTracks}
                </span>
                <span>
                  <span className="font-semibold text-slate-100">
                    Unique artists:{' '}
                  </span>
                  {data.uniqueArtists}
                </span>
              </div>

              <div className="rounded-lg border max-h-200 border-slate-800 bg-slate-900/60 overflow-y-auto">
                <table className="w-full text-xs text-slate-100">
                  <thead className="bg-slate-900/80 sticky top-0">
                    <tr className="text-sm font-medium">
                      <th className="px-3 py-2 text-left w-10"> </th>
                      <th className="px-3 py-2 text-left">Artist</th>
                      <th className="px-3 py-2 text-left w-16">Count</th>
                      <th className="px-3 py-2 text-left w-20">Share %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.artists.map((artist, idx) => {
                      const artistId = artist.url || `${artist.name}-${idx}`
                      const isExpanded = expanded[artistId]

                      return (
                        <Fragment key={artistId}>
                          <tr className="border-t border-slate-800 hover:bg-slate-800/50">
                            <td className="px-3 py-2 align-center">
                              <button
                                type="button"
                                className="text-slate-400 cursor-pointer hover:text-slate-100 text-3xl"
                                onClick={() => toggleArtist(artistId)}
                              >
                                {isExpanded ? '▾' : '▸'}
                              </button>
                            </td>
                            <td className="px-3 py-2 align-center">
                              {artist.url ? (
                                <a
                                  href={artist.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="text-emerald-400 hover:underline text-lg"
                                >
                                  {artist.name}
                                </a>
                              ) : (
                                artist.name
                              )}
                            </td>
                            <td className="px-3 py-2 align-center text-lg">
                              {artist.count}
                            </td>
                            <td className="px-3 py-2 align-center text-lg">
                              {artist.share.toFixed(2)}%
                            </td>
                          </tr>
                          {isExpanded && (
                            <tr>
                              <td colSpan={4} className="p-3 bg-slate-950/60">
                                <div className="text-[0.7rem] text-slate-300">
                                  <div className="font-semibold mb-1 text-sm">
                                    Songs in this playlist:
                                  </div>
                                  <ul className="list-disc ml-4 space-y-0.5">
                                    {artist.tracks.map((t) => (
                                      <li key={t.order}>
                                        {t.url ? (
                                          <a
                                            href={t.url}
                                            target="_blank"
                                            rel="noreferrer"
                                            className="text-emerald-300 hover:underline text-sm"
                                          >
                                            {t.name}
                                          </a>
                                        ) : (
                                          t.name
                                        )}
                                      </li>
                                    ))}
                                  </ul>
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Chart + Recommendations */}

            <div className="space-y-3">
              <div className="text-sm font-medium mb-2">
                Top {topArtists.length} artists by track count
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3 flex flex-col h-[360px]">
                <div className="flex-1 min-h-0">
                  {topArtists.length > 0 ? (
                    <Bar data={chartData} options={chartOptions} />
                  ) : (
                    <div className="text-xs text-slate-500 flex items-center justify-center h-full">
                      No artists to display.
                    </div>
                  )}
                </div>
              </div>

              <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4 space-y-3">
                <div className="flex flex-wrap items-center gap-2 justify-between">
                  <div className="flex items-center gap-3">
                    <div className="text-sm font-semibold flex items-center gap-2">
                      <span>Recommendations</span>
                      <div className="relative group inline-flex items-center">
                        <span className="text-[0.65rem] uppercase tracking-wide text-slate-400">
                          What’s this?
                        </span>
                        <div className="absolute left-0 top-5 z-10 hidden w-72 rounded-md border border-slate-800 bg-slate-900/95 p-3 text-[0.7rem] text-slate-200 shadow-lg shadow-black/50 group-hover:block">
                          <div className="font-semibold text-emerald-200 mb-1">
                            How we score
                          </div>
                          <div className="space-y-1">
                            <div>
                              confidence = (0.4 · artistScore + 0.25 · rankScore
                              + 0.2 · popularityScore + 0.15 · genreScore) ×
                              balancePenalty
                            </div>
                            <div className="text-slate-400">
                              artistScore compares how often the artist appears
                              in your playlist vs. the top artist; rankScore
                              rewards higher positions in the artist’s top
                              tracks; popularityScore is Spotify popularity
                              (0–1); genreScore measures overlap with your
                              playlist’s dominant genres; balancePenalty
                              down-weights artists that already take up a big
                              share of the playlist.
                            </div>
                            <div className="text-slate-400">
                              Higher % means higher confidence it fits. We fetch
                              up to 20 eligible artists and their top 10
                              tracks—results are good signals, not guarantees.
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                    {recMode === 'lesser' && derivedMaxArtistCount != null && (
                      <span className="text-[0.7rem] text-emerald-200 bg-emerald-500/10 px-2 py-0.5 rounded-sm">
                        ≤ {derivedMaxArtistCount} songs in playlist
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-slate-300">
                    <span className="text-[0.7rem] uppercase tracking-wide">
                      Focus
                    </span>
                    <div className="inline-flex rounded-md border border-slate-800 bg-slate-900/60">
                      <button
                        type="button"
                        onClick={() => setRecMode('lesser')}
                        className={`px-3 py-1 text-xs font-medium rounded-l-md transition ${
                          recMode === 'lesser'
                            ? 'bg-emerald-500 text-slate-900'
                            : 'text-slate-200 hover:bg-slate-800/80'
                        }`}
                      >
                        Lesser known
                      </button>
                      <button
                        type="button"
                        onClick={() => setRecMode('popular')}
                        className={`px-3 py-1 text-xs font-medium rounded-r-md transition ${
                          recMode === 'popular'
                            ? 'bg-emerald-500 text-slate-900'
                            : 'text-slate-200 hover:bg-slate-800/80'
                        }`}
                      >
                        More prevalent
                      </button>
                    </div>
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={requestRecommendations}
                    disabled={recsLoading || !playlistUrl.trim()}
                    className="inline-flex items-center gap-1 rounded-md border border-emerald-600 bg-emerald-500/10 px-3 py-1 text-[0.7rem] font-medium text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-60"
                  >
                    {recsLoading ? 'Fetching recs…' : 'Get recommendations'}
                  </button>
                  <button
                    type="button"
                    onClick={requestRecommendations}
                    disabled={recsLoading || !playlistUrl.trim()}
                    className="inline-flex items-center gap-1 rounded-md border border-slate-800 bg-slate-800/60 px-3 py-1 text-[0.7rem] font-medium text-slate-200 hover:bg-slate-800/90 disabled:opacity-60"
                  >
                    Randomize batch
                  </button>
                  {recs?.weights && (
                    <div className="text-[0.7rem] text-slate-400">
                      Weighted artist {Math.round(recs.weights.artist * 100)}%,
                      rank {Math.round(recs.weights.rank * 100)}%, genre{' '}
                      {Math.round(recs.weights.genre * 100)}%, popularity{' '}
                      {Math.round(recs.weights.popularity * 100)}%.
                    </div>
                  )}
                </div>

                {recsError && (
                  <div className="text-sm text-red-400">
                    Recommendations error: {recsError.message}
                  </div>
                )}
                {(showRecs || recsLoading || recs) && (
                  <div className="space-y-2">
                    {recsLoading && (
                      <div className="text-sm text-slate-400">
                        Fetching recommendations…
                      </div>
                    )}
                    {!recsLoading && recs && filteredTracks.length === 0 && (
                      <div className="text-sm text-slate-400">
                        No recommendations yet for this playlist—try a larger or
                        more varied playlist.
                      </div>
                    )}
                    {!recsLoading && recs && filteredTracks.length > 0 && (
                      <>
                        <div className="text-sm font-medium">
                          You might also like
                        </div>
                        <ul className="space-y-1 text-sm">
                          {filteredTracks.map((track) => (
                            <li
                              key={track.id}
                              className="flex flex-wrap justify-between gap-2 border-b border-slate-800/60 pb-2 last:border-0"
                            >
                              <div className="space-x-2">
                                {track.url ? (
                                  <a
                                    href={track.url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="text-emerald-300 hover:underline"
                                  >
                                    {track.name}
                                  </a>
                                ) : (
                                  <span className="text-slate-100">
                                    {track.name}
                                  </span>
                                )}
                                <span className="text-slate-400">·</span>
                                {track.artistUrl ? (
                                  <a
                                    href={track.artistUrl}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="text-slate-300 hover:underline"
                                  >
                                    {track.artistName}
                                  </a>
                                ) : (
                                  <span className="text-slate-300">
                                    {track.artistName}
                                  </span>
                                )}
                              </div>
                              <div className="flex items-center gap-2 text-[0.7rem] text-slate-500">
                                <span className="inline-flex items-center rounded-sm bg-emerald-500/10 px-2 py-0.5 text-emerald-200 font-semibold">
                                  {track.confidencePct.toFixed(1)}%
                                </span>
                                <span className="text-slate-400">
                                  Artist {track.scores.artistScore.toFixed(2)}{' '}
                                  (count {track.scores.artistCount}, share{' '}
                                  {track.scores.artistShare.toFixed(2)}) | Rank{' '}
                                  {track.scores.rankScore.toFixed(2)} | Genre{' '}
                                  {track.scores.genreScore.toFixed(2)} | Pop{' '}
                                  {track.scores.popularityScore.toFixed(2)}
                                </span>
                              </div>
                            </li>
                          ))}
                        </ul>
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default App
