import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:volt_core/volt_core.dart';

import '../application/booking_providers.dart';
import '../data/places_service.dart';
import '../domain/place.dart';

enum _Mode { search, map }

/// Picks one address, by search or by dropping a pin.
///
/// The search field is deliberately OUTSIDE the mode switch — one field, one
/// controller, one debounce timer, one session token, shared by both modes.
/// The only thing that differs is what happens when a suggestion is tapped:
/// in search mode it returns the place, in map mode it pans the map there so
/// the pin can then be nudged onto the actual gate. Duplicating the search
/// into each mode would have meant two debounce timers and two session
/// tokens, and a second token is the expensive kind of mistake — Google
/// treats a reused or unmatched token as no token at all and bills every
/// keystroke separately.
///
/// [initial] is whatever is already selected for this end of the trip, so
/// reopening the picker starts where the customer left off rather than back
/// at the city centre.
///
/// Returns a [Place] via Navigator.pop, or null if dismissed.
class AddressPickerScreen extends ConsumerStatefulWidget {
  const AddressPickerScreen({required this.title, this.initial, super.key});

  final String title;
  final Place? initial;

  @override
  ConsumerState<AddressPickerScreen> createState() =>
      _AddressPickerScreenState();
}

class _AddressPickerScreenState extends ConsumerState<AddressPickerScreen> {
  static const _debounce = Duration(milliseconds: 300);
  static const _minChars = 3;
  static const _pinZoom = 17.0;

  /// Roughly a metre in degrees. Used to decide whether the map has settled
  /// on a point we already have an address for.
  static const _samePointEpsilon = 1e-5;

  final _searchController = TextEditingController();

  _Mode _mode = _Mode.search;

  Timer? _debounceTimer;

  /// One token for this whole search, regenerated after each selection.
  ///
  /// Getting this wrong multiplies the Places bill by roughly the length of
  /// an address — see newSessionToken for the rules. Shared across both
  /// modes precisely so there is only ever one.
  String _sessionToken = newSessionToken();

  List<PlaceSuggestion> _suggestions = [];
  bool _searching = false;
  bool _resolving = false;
  String? _error;

  /// Set when the chosen or pinned location is outside the service area.
  /// Shown inline rather than returned, so the server never has to refuse it.
  String? _rejection;

  // --- Map mode state ---------------------------------------------------

  GoogleMapController? _mapController;
  LatLng? _mapCentre;
  Place? _pinnedPlace;
  bool _geocoding = false;

  /// The map is built on first entry to map mode and then kept alive, rather
  /// than rebuilt on every toggle. Maps SDK bills per map load, and the
  /// intended flow — search the area, then adjust the pin — crosses between
  /// modes at least once.
  bool _mapEverOpened = false;

  @override
  void initState() {
    super.initState();
    // Seeds map mode so it opens on the current selection. Also means the
    // first camera idle finds an address it already has and skips a
    // pointless reverse geocode.
    _pinnedPlace = widget.initial;
  }

  @override
  void dispose() {
    _debounceTimer?.cancel();
    _searchController.dispose();
    _mapController?.dispose();
    super.dispose();
  }

  // --- Search, shared by both modes -------------------------------------

  void _onQueryChanged(String raw) {
    // Cancel first: a keystroke during the wait replaces the pending call
    // rather than adding to it. Without this every character is a request,
    // which floods the network and makes results flicker as they race.
    _debounceTimer?.cancel();
    final query = raw.trim();

    setState(() {
      _error = null;
    });

    if (query.length < _minChars) {
      setState(() {
        _suggestions = [];
        _searching = false;
      });
      return;
    }

    // Shown immediately, not when the request starts, so the field never
    // looks frozen during the 300ms wait.
    setState(() => _searching = true);
    _debounceTimer = Timer(_debounce, () => _search(query));
  }

  Future<void> _search(String query) async {
    try {
      final results = await ref
          .read(placesServiceProvider)
          .suggest(query, _sessionToken);
      if (!mounted) return;
      // Ignore a response that arrived after the field moved on — the user
      // has typed more since, and a later request is already pending.
      if (_searchController.text.trim() != query) return;
      setState(() {
        _suggestions = results;
        _searching = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.message;
        _searching = false;
      });
    }
  }

  Future<void> _choose(PlaceSuggestion suggestion) async {
    if (_resolving) return;
    setState(() {
      _resolving = true;
      _error = null;
      _rejection = null;
    });

    try {
      // Same session token as the suggest calls. This is what closes the
      // billing session and bundles the whole search into one charge.
      final place = await ref
          .read(placesServiceProvider)
          .detail(suggestion.placeId, _sessionToken);
      // Session is spent. A reused token is treated as no token at all, so
      // the next search must start a fresh one.
      _sessionToken = newSessionToken();

      if (!mounted) return;

      if (_mode == _Mode.map) {
        // Pan rather than return. The whole point of searching from map mode
        // is to get near the right place and then put the pin on the actual
        // gate, which a search result cannot know about.
        _dismissSuggestions();
        _setPinned(place);
        await _mapController?.animateCamera(
          CameraUpdate.newLatLngZoom(LatLng(place.lat, place.lng), _pinZoom),
        );
      } else {
        _returnIfServiceable(place);
      }
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _resolving = false);
    }
  }

  void _dismissSuggestions() {
    // Cancel too, or a search that was already pending lands afterwards and
    // reopens the list over the map.
    _debounceTimer?.cancel();
    _searchController.clear();
    setState(() {
      _suggestions = [];
      _searching = false;
    });
    FocusScope.of(context).unfocus();
  }

  // --- Map mode ---------------------------------------------------------

  /// Where the map should open. The current pin if there is one — either
  /// passed in as [AddressPickerScreen.initial] or chosen during this session
  /// — and the service centre only when there is nothing better.
  LatLng _initialMapTarget(ServiceArea area) {
    final pinned = _pinnedPlace;
    if (pinned != null) return LatLng(pinned.lat, pinned.lng);
    return LatLng(area.centerLat, area.centerLng);
  }

  bool _alreadyResolved(LatLng point) {
    final pinned = _pinnedPlace;
    if (pinned == null) return false;
    return (pinned.lat - point.latitude).abs() < _samePointEpsilon &&
        (pinned.lng - point.longitude).abs() < _samePointEpsilon;
  }

  Future<void> _onCameraIdle() async {
    final centre = _mapCentre;
    if (centre == null || _geocoding) return;

    // Skip when the map has settled on a point we already have an address
    // for: opening on the existing selection, or the programmatic pan after
    // a search hit. Both would otherwise spend a billable reverse geocode to
    // replace a precise address with a coarser one.
    //
    // Compared by position rather than tracked with a "skip the next idle"
    // flag on purpose — a flag that is set but never consumed silently eats
    // the user's next real drag, whereas this is self-correcting.
    if (_alreadyResolved(centre)) return;

    setState(() {
      _geocoding = true;
      _error = null;
      _rejection = null;
      _pinnedPlace = null;
    });

    try {
      final place = await ref
          .read(placesServiceProvider)
          .reverseGeocode(centre.latitude, centre.longitude);
      if (!mounted) return;
      _setPinned(place);
    } on NoAddressAtPoint {
      if (!mounted) return;
      setState(() => _error = 'No address here. Try moving the pin.');
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _geocoding = false);
    }
  }

  /// Sets the pin and recomputes whether it is serviceable, so the message
  /// always describes the pin actually under the marker — after a drag, after
  /// a search hit, and on open.
  void _setPinned(Place place) {
    final area = ref.read(serviceAreaProvider).value;
    setState(() {
      _pinnedPlace = place;
      _rejection = area == null
          ? null
          : serviceAreaRejection(area, place.lat, place.lng);
    });
  }

  // --- Shared -----------------------------------------------------------

  /// Pre-checks the service area before returning. The server enforces the
  /// same rule, so this is purely so the customer hears it now rather than
  /// after a round trip — and so we never hand back a location the server is
  /// about to refuse.
  void _returnIfServiceable(Place place) {
    final area = ref.read(serviceAreaProvider).value;
    if (area != null) {
      final rejection = serviceAreaRejection(area, place.lat, place.lng);
      if (rejection != null) {
        setState(() => _rejection = rejection);
        return;
      }
    }
    // area == null means the service area never loaded. Let it through
    // rather than blocking the booking — the server will refuse it with a
    // proper message if it really is out of range.
    Navigator.of(context).pop(place);
  }

  void _toggleMode() {
    setState(() {
      _mode = _mode == _Mode.search ? _Mode.map : _Mode.search;
      if (_mode == _Mode.map) _mapEverOpened = true;
      _error = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    final areaAsync = ref.watch(serviceAreaProvider);
    final showSuggestions = _suggestions.isNotEmpty;

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.title),
        actions: [
          IconButton(
            tooltip: _mode == _Mode.search ? 'Drop a pin' : 'Search only',
            icon:
                Icon(_mode == _Mode.search ? Icons.map_outlined : Icons.list),
            onPressed: _toggleMode,
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            // One field for both modes. See the class doc.
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
              child: TextField(
                controller: _searchController,
                // Autofocus only in search mode: in map mode the customer
                // came to move a pin, and a keyboard covering the map is in
                // the way.
                autofocus: _mode == _Mode.search,
                textInputAction: TextInputAction.search,
                onChanged: _onQueryChanged,
                decoration: InputDecoration(
                  hintText: _mode == _Mode.search
                      ? 'Search for an address or landmark'
                      : 'Search to move the map',
                  prefixIcon: const Icon(Icons.search),
                  suffixIcon: _searching
                      ? const Padding(
                          padding: EdgeInsets.all(14),
                          child: SizedBox(
                            height: 18,
                            width: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          ),
                        )
                      : _searchController.text.isEmpty
                          ? null
                          : IconButton(
                              icon: const Icon(Icons.close),
                              onPressed: _dismissSuggestions,
                            ),
                ),
              ),
            ),
            if (_rejection != null)
              _InlineMessage(text: _rejection!, isError: true),
            if (_error != null) _InlineMessage(text: _error!, isError: true),
            if (_searching && !showSuggestions) const _SearchingHint(),
            Expanded(
              child: Stack(
                children: [
                  // Mode content underneath.
                  Positioned.fill(
                    child: _mode == _Mode.search
                        ? _EmptySearchState(
                            hasQuery: _searchController.text.trim().length >=
                                _minChars,
                            searching: _searching,
                          )
                        : areaAsync.when(
                            loading: () => const Center(
                                child: CircularProgressIndicator()),
                            error: (_, _) => const Center(
                              child: Padding(
                                padding: EdgeInsets.all(24),
                                child: Text(
                                  'Could not load the map area. Search for an '
                                  'address instead.',
                                  textAlign: TextAlign.center,
                                  style: TextStyle(
                                      color: AppColors.textSecondary),
                                ),
                              ),
                            ),
                            data: _buildMapPane,
                          ),
                  ),
                  // Suggestions sit on top in both modes — over the empty
                  // hint in search mode, over the map in map mode, which is
                  // the standard shape for search-on-a-map.
                  if (showSuggestions)
                    Positioned.fill(
                      child: ColoredBox(
                        color: Theme.of(context).scaffoldBackgroundColor,
                        child: ListView.separated(
                          itemCount: _suggestions.length,
                          separatorBuilder: (_, _) => const Divider(height: 1),
                          itemBuilder: (context, i) {
                            final suggestion = _suggestions[i];
                            return ListTile(
                              leading: const Icon(Icons.location_on_outlined,
                                  color: AppColors.navy),
                              title: Text(suggestion.title),
                              subtitle: suggestion.secondaryText.isEmpty
                                  ? null
                                  : Text(
                                      suggestion.secondaryText,
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                    ),
                              // Disabled while a selection resolves, so a
                              // second tap cannot fire a second Place
                              // Details call.
                              enabled: !_resolving,
                              onTap: () => _choose(suggestion),
                            );
                          },
                        ),
                      ),
                    ),
                  if (_resolving)
                    const Positioned(
                      left: 0,
                      right: 0,
                      top: 0,
                      child: LinearProgressIndicator(),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildMapPane(ServiceArea area) {
    // Built once, on first entry to map mode, then kept alive by staying in
    // the tree. IndexedStack is not used here because the search pane is
    // stateless — everything that must survive a toggle already lives on
    // this State object.
    if (!_mapEverOpened) return const SizedBox.shrink();

    return Column(
      children: [
        Expanded(
          child: Stack(
            alignment: Alignment.center,
            children: [
              GoogleMap(
                initialCameraPosition: CameraPosition(
                  target: _initialMapTarget(area),
                  zoom: _pinZoom,
                ),
                onMapCreated: (controller) => _mapController = controller,
                onCameraMove: (position) => _mapCentre = position.target,
                onCameraIdle: _onCameraIdle,
                myLocationEnabled: false,
                // Location permission is optional by design: denied is fine,
                // the map simply stays where it opened. Nothing in this flow
                // blocks on it.
                myLocationButtonEnabled: false,
                zoomControlsEnabled: false,
              ),
              // A fixed pin over a moving map, rather than a draggable
              // marker. Standard pattern, and it avoids the fiddliness of
              // grabbing a small target with a thumb.
              const IgnorePointer(
                child: Padding(
                  // Nudged up by half the icon so the point, not the centre
                  // of the glyph, sits on the map centre.
                  padding: EdgeInsets.only(bottom: 36),
                  child:
                      Icon(Icons.location_on, size: 44, color: AppColors.navy),
                ),
              ),
            ],
          ),
        ),
        _PinnedAddressBar(
          place: _pinnedPlace,
          geocoding: _geocoding,
          blocked: _rejection != null,
          onConfirm: () => _returnIfServiceable(_pinnedPlace!),
        ),
      ],
    );
  }
}

class _PinnedAddressBar extends StatelessWidget {
  const _PinnedAddressBar({
    required this.place,
    required this.geocoding,
    required this.blocked,
    required this.onConfirm,
  });

  final Place? place;
  final bool geocoding;
  final bool blocked;
  final VoidCallback onConfirm;

  @override
  Widget build(BuildContext context) {
    final pinned = place;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Theme.of(context).scaffoldBackgroundColor,
        border: const Border(top: BorderSide(color: AppColors.border)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (geocoding)
            const Row(
              children: [
                SizedBox(
                  height: 16,
                  width: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
                SizedBox(width: 12),
                Text('Finding this address…',
                    style: TextStyle(color: AppColors.textSecondary)),
              ],
            )
          else if (pinned != null)
            Text(pinned.address,
                style: const TextStyle(fontWeight: FontWeight.w500))
          else
            const Text('Move the map to place the pin',
                style: TextStyle(color: AppColors.textSecondary)),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              // Blocked as well as null-checked: the out-of-area message is
              // already on screen, so leaving the button live only to refuse
              // the tap would be worse than disabling it.
              onPressed:
                  pinned == null || geocoding || blocked ? null : onConfirm,
              child: const Text('Confirm this location'),
            ),
          ),
        ],
      ),
    );
  }
}

class _InlineMessage extends StatelessWidget {
  const _InlineMessage({required this.text, required this.isError});

  final String text;
  final bool isError;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(8),
        color: (isError ? AppColors.danger : AppColors.navy)
            .withValues(alpha: 0.08),
      ),
      child: Text(
        text,
        style: TextStyle(
          fontSize: 13,
          color: isError ? AppColors.danger : AppColors.navy,
        ),
      ),
    );
  }
}

/// Appears only if a search is taking a while, and only against a remote
/// backend. The free plan sleeps, so the first search of a session can sit
/// behind a cold start far longer than the 300ms debounce suggests.
class _SearchingHint extends StatefulWidget {
  const _SearchingHint();

  @override
  State<_SearchingHint> createState() => _SearchingHintState();
}

class _SearchingHintState extends State<_SearchingHint> {
  bool _show = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    if (AppConfig.isRemote) {
      _timer = Timer(const Duration(seconds: 5), () {
        if (mounted) setState(() => _show = true);
      });
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_show) return const SizedBox.shrink();
    return const Padding(
      padding: EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Text(
        'Waking up the server, this can take a minute on the first search.',
        style: TextStyle(color: AppColors.textSecondary, fontSize: 13),
      ),
    );
  }
}

class _EmptySearchState extends StatelessWidget {
  const _EmptySearchState({required this.hasQuery, required this.searching});

  final bool hasQuery;
  final bool searching;

  @override
  Widget build(BuildContext context) {
    if (searching) return const SizedBox.shrink();
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Text(
          hasQuery
              ? 'No matches. Try a nearby landmark, or drop a pin instead.'
              : 'Type at least 3 characters, or drop a pin on the map.',
          textAlign: TextAlign.center,
          style: const TextStyle(color: AppColors.textSecondary),
        ),
      ),
    );
  }
}
