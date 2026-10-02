from datetime import datetime, timedelta
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from datetime import date

from .graficos import escala, intervalos_do_grafico, montar_grafico
from .models import InstagramConnection, SeguidoresDia
from .views import (
    _buscar_midias_desde, _buscar_visualizacoes_conta, _motivo_erro_insights, _resolver_periodo, _sincronizar_seguidores,
    _somar_seguidores,
)


def _local(*args):
    return timezone.make_aware(datetime(*args))


def _congelar_em(*args):
    return mock.patch('core.views.timezone.now', return_value=_local(*args))


def _fmt(momento):
    return timezone.localtime(momento).strftime('%d/%m/%Y %H:%M')


class ResolverPeriodoTests(SimpleTestCase):
    def test_hoje_compara_com_ontem_inteiro(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('hoje', None, None)
        self.assertEqual(_fmt(p.desde), '24/09/2026 00:00')
        self.assertEqual(_fmt(p.ate), '24/09/2026 11:25')
        self.assertEqual(_fmt(p.anterior_desde), '23/09/2026 00:00')
        self.assertEqual(_fmt(p.anterior_ate), '23/09/2026 23:59')
        self.assertEqual(p.label_comparacao, 'vs. ontem')

    def test_semana_compara_ate_o_mesmo_dia_da_semana_passada(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('semana', None, None)
        self.assertEqual(_fmt(p.desde), '21/09/2026 00:00')
        self.assertEqual(_fmt(p.anterior_desde), '14/09/2026 00:00')
        self.assertEqual(_fmt(p.anterior_ate), '17/09/2026 23:59')
        self.assertEqual(p.label_comparacao, 'vs. semana passada até qui')

    def test_mes_compara_ate_o_mesmo_dia_do_mes_passado(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('mes', None, None)
        self.assertEqual(_fmt(p.desde), '01/09/2026 00:00')
        self.assertEqual(_fmt(p.anterior_desde), '01/08/2026 00:00')
        self.assertEqual(_fmt(p.anterior_ate), '24/08/2026 23:59')
        self.assertEqual(p.label_comparacao, 'vs. mês passado até 24/08')

    def test_mes_no_dia_31_usa_o_ultimo_dia_do_mes_anterior(self):
        with _congelar_em(2026, 3, 31, 9, 0):
            p = _resolver_periodo('mes', None, None)
        self.assertEqual(_fmt(p.anterior_ate), '28/02/2026 23:59')

    def test_mes_em_janeiro_compara_com_dezembro_do_ano_anterior(self):
        with _congelar_em(2026, 1, 10, 8, 0):
            p = _resolver_periodo('mes', None, None)
        self.assertEqual(_fmt(p.anterior_desde), '01/12/2025 00:00')
        self.assertEqual(_fmt(p.anterior_ate), '10/12/2025 23:59')

    def test_periodo_desconhecido_usa_este_mes(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('mes_passado', None, None)
        self.assertEqual(p.chave, 'mes')

    def test_periodo_compara_com_os_mesmos_dias_anteriores(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('periodo', '2026-09-20', '2026-09-24')
        self.assertEqual(_fmt(p.ate), '24/09/2026 11:25')
        self.assertEqual(_fmt(p.anterior_desde), '15/09/2026 00:00')
        self.assertEqual(_fmt(p.anterior_ate), '19/09/2026 23:59')
        self.assertEqual(p.label_comparacao, 'vs. 5 dias anteriores')

    def test_periodo_com_datas_invertidas_e_corrigido(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('periodo', '2026-08-15', '2026-08-01')
        self.assertEqual(p.label, '01/08/2026 – 15/08/2026')

    def test_periodo_invalido_usa_este_mes(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('periodo', 'xx', 'yy')
        self.assertEqual(p.chave, 'mes')


def _resposta_erro(status, corpo):
    resp = mock.Mock(status_code=status)
    resp.json.return_value = corpo
    return resp


class MotivoErroInsightsTests(SimpleTestCase):
    def test_post_anterior_a_conta_profissional(self):
        resp = _resposta_erro(400, {'error': {'code': 100, 'error_subcode': 2108006, 'message': 'Media Posted Before Business Account Conversion'}})
        self.assertIn('antes da conta virar profissional', _motivo_erro_insights(resp))

    def test_permissao_nao_concedida(self):
        resp = _resposta_erro(403, {'error': {'code': 10, 'message': 'Application does not have permission for this action'}})
        self.assertIn('permissão de estatísticas', _motivo_erro_insights(resp))

    def test_token_expirado(self):
        resp = _resposta_erro(401, {'error': {'code': 190, 'message': 'Error validating access token'}})
        self.assertIn('expirou', _motivo_erro_insights(resp))

    def test_erro_desconhecido_mostra_mensagem_do_instagram(self):
        resp = _resposta_erro(400, {'error': {'code': 100, 'message': '(#100) The metric views is not supported'}})
        self.assertIn('The metric views is not supported', _motivo_erro_insights(resp))

    def test_resposta_sem_json(self):
        resp = mock.Mock(status_code=502)
        resp.json.side_effect = ValueError
        self.assertIn('HTTP 502', _motivo_erro_insights(resp))


class IntervalosDoGraficoTests(SimpleTestCase):
    hoje = date(2026, 9, 24)

    def test_hoje_mostra_os_ultimos_7_dias(self):
        subtitulo, intervalos = intervalos_do_grafico('hoje', self.hoje, self.hoje, self.hoje)
        self.assertEqual(subtitulo, 'Últimos 7 dias')
        self.assertEqual([i.rotulo for i in intervalos], ['sex 18', 'sáb 19', 'dom 20', 'seg 21', 'ter 22', 'qua 23', 'qui 24'])

    def test_semana_mostra_8_semanas_comecando_na_segunda(self):
        _, intervalos = intervalos_do_grafico('semana', self.hoje, self.hoje, self.hoje)
        self.assertEqual(len(intervalos), 8)
        self.assertEqual((intervalos[0].inicio, intervalos[0].fim), (date(2026, 8, 3), date(2026, 8, 9)))
        self.assertEqual((intervalos[-1].inicio, intervalos[-1].fim), (date(2026, 9, 21), self.hoje))

    def test_mes_mostra_os_meses_do_ano_ate_hoje(self):
        subtitulo, intervalos = intervalos_do_grafico('mes', self.hoje, self.hoje, self.hoje)
        self.assertEqual(subtitulo, 'Meses de 2026')
        self.assertEqual([i.rotulo for i in intervalos], ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set'])
        self.assertEqual(intervalos[1].fim, date(2026, 2, 28))
        self.assertEqual(intervalos[-1].fim, self.hoje)

    def test_periodo_curto_e_por_dia_e_longo_e_por_mes(self):
        subtitulo, intervalos = intervalos_do_grafico('periodo', date(2026, 9, 1), date(2026, 9, 10), self.hoje)
        self.assertEqual((subtitulo, len(intervalos)), ('Por dia', 10))
        subtitulo, intervalos = intervalos_do_grafico('periodo', date(2026, 7, 1), date(2026, 8, 31), self.hoje)
        self.assertEqual((subtitulo, len(intervalos)), ('Por semana', 9))
        subtitulo, intervalos = intervalos_do_grafico('periodo', date(2025, 11, 15), date(2026, 9, 30), self.hoje)
        self.assertEqual(subtitulo, 'Por mês')
        self.assertEqual(intervalos[0].rotulo, 'nov/25')
        self.assertEqual(intervalos[0].inicio, date(2025, 11, 15))
        self.assertEqual(intervalos[-1].fim, self.hoje)


class EscalaEGraficoTests(SimpleTestCase):
    def test_escala_usa_numeros_redondos(self):
        self.assertEqual(escala(0, 37), [0, 10, 20, 30, 40])
        self.assertEqual(escala(0, 2), [0, 1, 2])
        self.assertEqual(escala(-3, 12), [-5, 0, 5, 10, 15])
        self.assertEqual(escala(0, 0), [0, 1])

    def test_barras_negativas_crescem_para_baixo_a_partir_do_zero(self):
        _, intervalos = intervalos_do_grafico('hoje', date(2026, 9, 24), date(2026, 9, 24), date(2026, 9, 24))
        grafico = montar_grafico('x', intervalos, [10, -5, None, 0, 15, 3, 1])
        self.assertEqual(grafico['base'], 25.0)
        positiva, negativa, vazia = grafico['barras'][:3]
        self.assertEqual((positiva['inferior'], positiva['altura']), (25.0, 50.0))
        self.assertEqual((negativa['inferior'], negativa['altura']), (0.0, 25.0))
        self.assertTrue(negativa['negativo'])
        self.assertNotIn('altura', vazia)

    def test_sem_nenhum_dado_fica_vazio(self):
        _, intervalos = intervalos_do_grafico('hoje', date(2026, 9, 24), date(2026, 9, 24), date(2026, 9, 24))
        self.assertTrue(montar_grafico('x', intervalos, [None] * 7)['vazio'])


class SeguidoresTests(TestCase):
    def test_soma_marca_incompleto_quando_falta_dia_encerrado(self):
        por_dia = {date(2026, 9, 21): 3, date(2026, 9, 23): 2}
        self.assertEqual(_somar_seguidores(por_dia, date(2026, 9, 21), date(2026, 9, 24), date(2026, 9, 24)), (5, False))
        por_dia[date(2026, 9, 22)] = 1
        self.assertEqual(_somar_seguidores(por_dia, date(2026, 9, 21), date(2026, 9, 24), date(2026, 9, 24)), (6, True))
        self.assertEqual(_somar_seguidores({}, date(2026, 9, 21), date(2026, 9, 24), date(2026, 9, 24)), (None, False))

    def test_sincronizar_grava_cada_dia_pelo_end_time(self):
        from django.contrib.auth.models import User
        usuario = User.objects.create(username='teste')
        conexao = InstagramConnection.objects.create(user=usuario, instagram_user_id='123', access_token='t')
        resposta = mock.Mock(ok=True)
        resposta.json.return_value = {'data': [{'values': [
            {'value': 4, 'end_time': '2026-09-22T07:00:00+0000'},
            {'value': -1, 'end_time': '2026-09-23T07:00:00+0000'},
        ]}]}
        with mock.patch('core.views.requests.get', return_value=resposta):
            _sincronizar_seguidores(conexao)
            resposta.json.return_value['data'][0]['values'][1]['value'] = 2
            _sincronizar_seguidores(conexao)
        dias = dict(SeguidoresDia.objects.values_list('data', 'novos_seguidores'))
        self.assertEqual(dias, {date(2026, 9, 21): 4, date(2026, 9, 22): 2})


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class DashboardRespostasInesperadasTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.usuario = User.objects.create(username='dono')
        InstagramConnection.objects.create(user=self.usuario, instagram_user_id='999', access_token='t')
        self.client.force_login(self.usuario)

    def _get(self, respostas, params=None):
        def fake_get(url, params=None, timeout=None):
            for sufixo, corpo, ok in respostas:
                if url.endswith(sufixo):
                    resp = mock.Mock(ok=ok, status_code=200 if ok else 400, text='')
                    resp.json.return_value = corpo
                    return resp
            resp = mock.Mock(ok=True, status_code=200, text='')
            resp.json.return_value = {}
            return resp

        with mock.patch('core.views.requests.get', side_effect=fake_get):
            return self.client.get('/dashboard/dados/', params or {})

    def _video(self):
        agora = timezone.now().strftime('%Y-%m-%dT%H:%M:%S+0000')
        return {'id': '1', 'timestamp': agora, 'media_type': 'VIDEO', 'permalink': 'x'}

    def test_dashboard_abre_em_este_mes(self):
        resp = self.client.get('/dashboard/')
        self.assertEqual(resp.context['periodo_atual'], 'mes')
        self.assertContains(resp, '<option value="mes" selected>')

    def test_pagina_abre_na_hora_com_o_perfil_salvo_e_carrega_o_resto_depois(self):
        InstagramConnection.objects.filter(user=self.usuario).update(
            instagram_username='xbiomed.br', perfil_nome='Xbiomed | Suplementos Premium',
            perfil_seguidores=7600, perfil_posts=4, perfil_seguindo=1400)
        with mock.patch('core.views.requests.get') as get:
            resp = self.client.get('/dashboard/', {'periodo': 'semana'})
        get.assert_not_called()
        self.assertContains(resp, 'Xbiomed | Suplementos Premium')
        self.assertContains(resp, '@xbiomed.br')
        self.assertContains(resp, '<dd title="7.600">7,6 mil</dd>', html=True)
        self.assertContains(resp, 'data-carregar="/dashboard/dados/?periodo=semana"')

        # Os dados chegam depois e atualizam o perfil salvo para a próxima abertura.
        dados = self._get([('/me', {'name': 'Xbiomed', 'username': 'xbiomed.br', 'profile_picture_url': 'https://f',
                                    'followers_count': 7700, 'media_count': 5, 'follows_count': 1400}, True)])
        self.assertContains(dados, 'data-substitui="perfilTopo"')
        conexao = InstagramConnection.objects.get(user=self.usuario)
        self.assertEqual((conexao.perfil_nome, conexao.perfil_seguidores, conexao.perfil_posts, conexao.perfil_foto),
                         ('Xbiomed', 7700, 5, 'https://f'))

        # Se o Instagram falhar, a última leitura boa é mantida.
        self._get([('/me', {}, False)])
        conexao.refresh_from_db()
        self.assertEqual(conexao.perfil_seguidores, 7700)

    def test_topo_mostra_nome_arroba_e_numeros_do_perfil(self):
        resp = self._get([('/me', {
            'name': 'Cejana Baiocchi Souza', 'username': 'dra.cejana', 'profile_picture_url': 'https://foto',
            'followers_count': 74912, 'media_count': 364, 'follows_count': 634,
        }, True)])
        self.assertContains(resp, '<h2 class="profile-hero-name">Cejana Baiocchi Souza</h2>', html=True)
        self.assertContains(resp, '@dra.cejana')
        self.assertContains(resp, '<dd title="74.912">74,9 mil</dd>', html=True)
        self.assertContains(resp, '<dd title="364">364</dd>', html=True)
        self.assertContains(resp, '<dd title="634">634</dd>', html=True)

    def test_cards_ganham_minigrafico_e_visualizacoes_somam_as_faixas(self):
        with _congelar_em(2026, 9, 28, 15, 0):
            resp = self._get([('/insights', {'data': [{'total_value': {'value': 100}}]}, True)])
        # Este mês (01 a 28/09) e o mesmo trecho de agosto viram 7 faixas cada: 7 × 100 visualizações.
        self.assertEqual(resp.context['visualizacoes_total'], 700)
        self.assertEqual(resp.context['comparacao_visualizacoes'], {'direcao': 'equal', 'valor': 0})
        self.assertEqual(len(resp.context['minigrafico_visualizacoes']['fatias']), 14)
        self.assertContains(resp, 'class="spark"', count=3)  # sem nenhum dia de seguidores salvo, esse card fica sem
        self.assertContains(resp, 'aria-label="Este mês, 25–28/09: 100 visualizações"')

    def test_topo_sem_resposta_do_perfil_usa_o_arroba_salvo(self):
        InstagramConnection.objects.filter(user=self.usuario).update(instagram_username='salvo')
        resp = self._get([('/me', {}, False)])
        self.assertContains(resp, '<h2 class="profile-hero-name">salvo</h2>', html=True)
        self.assertContains(resp, '<dd>&mdash;</dd>', html=True)

    def test_fotos_e_carrosseis_tambem_mostram_visualizacoes(self):
        agora = timezone.now().strftime('%Y-%m-%dT%H:%M:%S+0000')
        posts = [
            {'id': '7', 'timestamp': agora, 'media_type': 'IMAGE', 'permalink': 'x', 'media_url': 'https://x/7.jpg'},
            {'id': '8', 'timestamp': agora, 'media_type': 'CAROUSEL_ALBUM', 'permalink': 'x', 'media_url': 'https://x/8.jpg'},
        ]
        resp = self._get([
            ('/media', {'data': posts}, True),
            ('/7/insights', {'data': [{'name': 'views', 'values': [{'value': 4321}]}]}, True),
            ('/8/insights', {'data': [{'name': 'views', 'total_value': {'value': 987}}]}, True),
        ])
        self.assertContains(resp, '4.321 visualizações')
        self.assertContains(resp, '4,3 mil')
        self.assertContains(resp, '987 visualizações')

    def _posts(self, quantidade):
        agora = timezone.now()
        return [{
            'id': str(i), 'media_type': 'IMAGE', 'permalink': 'x', 'media_url': f'https://x/{i}.jpg',
            'timestamp': (agora - timedelta(hours=i)).strftime('%Y-%m-%dT%H:%M:%S+0000'),
            'like_count': (i * 37) % 101,
        } for i in range(quantidade)]

    def _ids_exibidos(self, resp):
        return [m['id'] for m in resp.context['midias']]

    def test_ranking_padrao_e_mais_recentes(self):
        resp = self._get([('/media', {'data': self._posts(60)}, True)])
        self.assertEqual(resp.context['ordem_atual'], 'recentes')
        self.assertEqual(self._ids_exibidos(resp), [str(i) for i in range(12)])

    def test_ranking_por_curtidas_considera_as_ultimas_50(self):
        posts = self._posts(60)
        with mock.patch('core.views.requests.get') as get:
            def responder(url, params=None, timeout=None):
                resp = mock.Mock(ok=True, status_code=200, text='')
                resp.json.return_value = {'data': posts} if url.endswith('/media') else {}
                return resp
            get.side_effect = responder
            resp = self.client.get('/dashboard/dados/', {'ordem': 'curtidas'})
        esperado = sorted(posts[:50], key=lambda m: m['like_count'], reverse=True)[:12]
        self.assertEqual(self._ids_exibidos(resp), [m['id'] for m in esperado])
        self.assertContains(resp, 'Entre as últimas 50 publicações')

    def test_ranking_por_visualizacoes_deixa_sem_dado_por_ultimo(self):
        posts = self._posts(4)
        views = {'0': 10, '1': None, '2': 900, '3': 55}

        def responder(url, params=None, timeout=None):
            resp = mock.Mock(ok=True, status_code=200, text='')
            if url.endswith('/media'):
                resp.json.return_value = {'data': posts}
            elif url.endswith('/insights') and url.rsplit('/', 2)[-2] in views:
                valor = views[url.rsplit('/', 2)[-2]]
                if valor is None:
                    resp.ok, resp.status_code = False, 400
                    resp.json.return_value = {'error': {'code': 100, 'error_subcode': 2108006}}
                else:
                    resp.json.return_value = {'data': [{'name': 'views', 'values': [{'value': valor}]}]}
            else:
                resp.json.return_value = {}
            return resp

        with mock.patch('core.views.requests.get', side_effect=responder):
            resp = self.client.get('/dashboard/dados/', {'ordem': 'visualizacoes'})
        self.assertEqual(self._ids_exibidos(resp), ['2', '3', '0', '1'])

    def test_ordem_invalida_volta_para_recentes(self):
        resp = self._get([], {'ordem': 'xyz'})
        self.assertEqual(resp.context['ordem_atual'], 'recentes')

    def test_post_sem_media_url_nao_derruba_a_pagina(self):
        resp = self._get([('/media', {'data': [self._video()]}, True)])
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'class="media-card"')

    def test_visualizacoes_com_total_value_nulo(self):
        resp = self._get([
            ('/media', {'data': [self._video()]}, True),
            ('/1/insights', {'data': [{'name': 'views', 'total_value': None}]}, True),
        ])
        self.assertEqual(resp.status_code, 200)

    def test_erro_de_visualizacoes_com_mensagem_nula(self):
        resp = self._get([
            ('/media', {'data': [self._video()]}, True),
            ('/1/insights', {'error': {'code': 100, 'message': None}}, False),
        ])
        self.assertEqual(resp.status_code, 200)

    def test_erro_inesperado_mostra_aviso_em_vez_de_500(self):
        with mock.patch('core.views._somar_engajamento', side_effect=RuntimeError('boom')), \
                self.assertLogs('core.views', level='ERROR'):
            resp = self._get([])
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Não foi possível carregar os dados do Instagram')

    def test_token_longo_e_aceito(self):
        conexao = InstagramConnection.objects.get(user=self.usuario)
        conexao.access_token = 'I' * 400
        conexao.save()
        conexao.refresh_from_db()
        self.assertEqual(len(conexao.access_token), 400)


class VisualizacoesContaTests(SimpleTestCase):
    conexao = InstagramConnection(instagram_user_id='123', access_token='t')

    def _resposta(self, valor):
        resp = mock.Mock(ok=True)
        resp.json.return_value = {'data': [{'name': 'views', 'total_value': {'value': valor}}]}
        return resp

    def test_periodo_longo_e_somado_em_partes_de_30_dias(self):
        with mock.patch('core.views.requests.get', side_effect=[self._resposta(100), self._resposta(40)]) as get:
            total = _buscar_visualizacoes_conta(self.conexao, _local(2026, 7, 1), _local(2026, 8, 15))
        self.assertEqual(total, 140)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0].kwargs['params']['metric_type'], 'total_value')
        primeira, segunda = (c.kwargs['params'] for c in get.call_args_list)
        self.assertEqual(primeira['until'], segunda['since'])
        self.assertLessEqual(primeira['until'] - primeira['since'], 30 * 86400)

    def test_recusa_do_instagram_vira_sem_dados(self):
        recusa = mock.Mock(ok=False, status_code=400, text='{"error": {}}')
        with mock.patch('core.views.requests.get', return_value=recusa):
            self.assertIsNone(_buscar_visualizacoes_conta(self.conexao, _local(2026, 9, 1), _local(2026, 9, 24)))


class MinigraficoTests(SimpleTestCase):
    def test_divide_o_periodo_em_ate_7_faixas_seguidas(self):
        from .minigrafico import dividir_em_baldes
        faixas = dividir_em_baldes(date(2026, 9, 1), date(2026, 9, 28))
        self.assertEqual(len(faixas), 7)
        self.assertEqual(faixas[0], (date(2026, 9, 1), date(2026, 9, 4)))
        self.assertEqual(faixas[-1][1], date(2026, 9, 28))
        for (_, fim), (inicio, _) in zip(faixas, faixas[1:]):
            self.assertEqual(inicio - fim, timedelta(days=1))
        self.assertEqual(dividir_em_baldes(date(2026, 9, 28), date(2026, 9, 28)),
                         [(date(2026, 9, 28), date(2026, 9, 28))])

    def test_descricao_das_faixas(self):
        from .minigrafico import descrever_balde
        self.assertEqual(descrever_balde(date(2026, 9, 5), date(2026, 9, 5)), '05/09')
        self.assertEqual(descrever_balde(date(2026, 9, 1), date(2026, 9, 7)), '01–07/09')
        self.assertEqual(descrever_balde(date(2026, 8, 30), date(2026, 9, 2)), '30/08–02/09')

    def test_linha_anterior_e_atual_com_ponto_final(self):
        from .minigrafico import montar_minigrafico
        grafico = montar_minigrafico([('a', 10), ('b', 30)], [('c', 20), ('d', 0)])
        self.assertTrue(grafico['linha_anterior'].startswith('M0.00,'))
        self.assertEqual(grafico['linha_anterior'].count('C'), 2)  # vai até o primeiro ponto atual
        self.assertEqual(grafico['linha_atual'].count('C'), 1)
        self.assertTrue(grafico['area'].endswith('Z'))
        self.assertEqual(grafico['final'], {'x': 100, 'y': 87.5})  # menor valor fica embaixo
        self.assertEqual([f['atual'] for f in grafico['fatias']], [False, False, True, True])
        self.assertAlmostEqual(sum(f['largura'] for f in grafico['fatias']), 100)

    def test_faixas_sem_dado(self):
        from .minigrafico import montar_minigrafico
        # No período atual, faltar dado tira o gráfico; no anterior, só a faixa sai.
        self.assertIsNone(montar_minigrafico([('a', 1)], [('b', 3), ('c', None)]))
        self.assertIsNone(montar_minigrafico([('a', 1)], []))
        grafico = montar_minigrafico([('a', None), ('b', 2)], [('c', 3), ('d', 4)])
        self.assertEqual([f['descricao'] for f in grafico['fatias']], ['b', 'c', 'd'])

    def test_um_ponto_so_no_periodo_atual_liga_ao_anterior_na_cor_do_card(self):
        from .minigrafico import montar_minigrafico
        hoje = montar_minigrafico([('ontem', 5)], [('hoje', 5)])
        self.assertEqual(hoje['linha_anterior'], '')
        self.assertEqual(hoje['linha_atual'].count('C'), 1)
        self.assertEqual(hoje['final']['y'], 50)
        self.assertEqual(montar_minigrafico([], [('hoje', 5)])['linha_atual'], 'M100.00,20.00')


class NumeroCompactoTests(SimpleTestCase):
    def test_formato_estilo_instagram(self):
        from .templatetags.nexora import compacto
        casos = {0: '0', 999: '999', 1000: '1 mil', 1523: '1,5 mil', 12345: '12 mil',
                 999950: '1 mi', 1250000: '1,2 mi', -2300: '-2,3 mil', None: None}
        for valor, esperado in casos.items():
            self.assertEqual(compacto(valor), esperado, valor)
        detalhados = {74912: '74,9 mil', 12345: '12,3 mil', 150000: '150 mil', 40000: '40 mil', 1_250_000: '1,2 mi'}
        for valor, esperado in detalhados.items():
            self.assertEqual(compacto(valor, True), esperado, valor)


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class AgendaTests(TestCase):
    def setUp(self):
        import tempfile
        from django.contrib.auth.models import User
        # As mídias vão para o disco: cada teste usa uma pasta temporária própria.
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        configuracao = override_settings(MEDIA_ROOT=pasta.name)
        configuracao.enable()
        self.addCleanup(configuracao.disable)
        self.usuario = User.objects.create(username='agenda')
        self.outro = User.objects.create(username='outro')
        self.client.force_login(self.usuario)

    def test_calendario_de_setembro_de_2026_comeca_no_domingo_30_de_agosto(self):
        resp = self.client.get('/programacao/', {'mes': '2026-09', 'dia': '2026-09-24'})
        self.assertEqual(resp.status_code, 200)
        semanas = resp.context['semanas']
        self.assertEqual(semanas[0][0]['data'], date(2026, 8, 30))
        self.assertTrue(semanas[0][0]['fora_do_mes'])
        self.assertEqual(semanas[0][2]['data'], date(2026, 9, 1))
        self.assertEqual(resp.context['titulo_mes'], 'Setembro 2026')
        self.assertEqual(resp.context['titulo_selecionado'], 'Quinta, 24 de setembro')
        self.assertEqual((resp.context['mes_anterior'], resp.context['mes_seguinte']), ('2026-08', '2026-10'))

    def test_virada_de_ano_na_navegacao(self):
        resp = self.client.get('/programacao/', {'mes': '2026-12'})
        self.assertEqual(resp.context['mes_seguinte'], '2027-01')
        resp = self.client.get('/programacao/', {'mes': '2026-01'})
        self.assertEqual(resp.context['mes_anterior'], '2025-12')

    def test_adicionar_concluir_e_excluir_item(self):
        from .models import ItemAgenda
        resp = self.client.post('/programacao/itens/', {'formato': 'reels', 'data': '2026-09-24', 'titulo': 'Gravar reels', 'cor': '#f5426f'})
        self.assertRedirects(resp, '/programacao/?mes=2026-09&dia=2026-09-24', fetch_redirect_response=False)
        item = ItemAgenda.objects.get(usuario=self.usuario)
        self.assertEqual(item.cor, '#f5426f')

        pagina = self.client.get('/programacao/', {'mes': '2026-09', 'dia': '2026-09-24'})
        self.assertContains(pagina, 'Gravar reels')
        self.assertContains(pagina, 'style="--cor: #f5426f"')
        self.assertNotContains(pagina, 'type="time"')

        self.client.post(f'/programacao/itens/{item.id}/concluir/')
        item.refresh_from_db()
        self.assertTrue(item.concluido)

        self.client.post(f'/programacao/itens/{item.id}/excluir/')
        self.assertFalse(ItemAgenda.objects.exists())

    def test_item_sem_titulo_ou_data_invalida_nao_e_criado(self):
        from .models import ItemAgenda
        self.client.post('/programacao/itens/', {'formato': 'reels', 'data': '2026-09-24', 'titulo': '   '})
        self.client.post('/programacao/itens/', {'formato': 'reels', 'data': 'ontem', 'titulo': 'x'})
        self.assertFalse(ItemAgenda.objects.exists())

    def test_editar_titulo_dia_e_cor(self):
        from .models import ItemAgenda
        item = ItemAgenda.objects.create(usuario=self.usuario, data=date(2026, 10, 1), titulo='olá')
        self.assertEqual(item.cor, '#7c5cff')
        resp = self.client.post(f'/programacao/itens/{item.id}/editar/',
                                {'formato': 'reels', 'titulo': 'Olá, gravar stories', 'data': '2026-10-02', 'cor': '#3ddc84'})
        self.assertRedirects(resp, '/programacao/?mes=2026-10&dia=2026-10-02', fetch_redirect_response=False)
        item.refresh_from_db()
        self.assertEqual((item.titulo, item.data, item.cor), ('Olá, gravar stories', date(2026, 10, 2), '#3ddc84'))

        # Título vazio, dia inválido e cor fora da paleta mantêm o que já estava.
        self.client.post(f'/programacao/itens/{item.id}/editar/', {'formato': 'reels', 'titulo': ' ', 'data': 'ontem', 'cor': 'red'})
        item.refresh_from_db()
        self.assertEqual((item.titulo, item.data, item.cor), ('Olá, gravar stories', date(2026, 10, 2), '#3ddc84'))

    def _arquivo(self, nome, tipo, dados=b'dados'):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(nome, dados, content_type=tipo)

    def test_item_com_legenda_e_varias_imagens_e_videos(self):
        from .models import ItemAgenda
        self.client.post('/programacao/itens/', {
            'data': '2026-10-01', 'titulo': 'Post lançamento', 'formato': 'carrossel', 'legenda': 'Texto do post\ncom duas linhas',
            'midias': [self._arquivo('capa.png', 'image/png', b'\x89PNG capa'),
                       self._arquivo('reels.mp4', 'video/mp4', b'0123456789'),
                       self._arquivo('foto.jpg', 'image/jpeg')],
        })
        item = ItemAgenda.objects.get(usuario=self.usuario)
        self.assertEqual(item.legenda, 'Texto do post\ncom duas linhas')
        capa, reels, foto = item.midias.all()
        self.assertEqual([m.tipo for m in (capa, reels, foto)], ['image/png', 'video/mp4', 'image/jpeg'])
        self.assertTrue(reels.e_video)

        arquivo = self.client.get(f'/programacao/midias/{capa.id}/')
        self.assertEqual((arquivo.status_code, arquivo['Content-Type'], b''.join(arquivo.streaming_content)),
                         (200, 'image/png', b'\x89PNG capa'))
        parte = self.client.get(f'/programacao/midias/{reels.id}/', HTTP_RANGE='bytes=2-5')
        self.assertEqual((parte.status_code, b''.join(parte.streaming_content), parte['Content-Range']),
                         (206, b'2345', 'bytes 2-5/10'))

        pagina = self.client.get('/programacao/', {'mes': '2026-10', 'dia': '2026-10-01'})
        self.assertContains(pagina, f'<img src="/programacao/midias/{capa.id}/" alt="" loading="lazy">', html=True)
        self.assertContains(pagina, f'src="/programacao/midias/{reels.id}/#t=0.1"')
        self.assertContains(pagina, '<span class="day-item-caption">Texto do post\ncom duas linhas</span>', html=True)
        self.assertContains(pagina, f'&quot;id&quot;: {foto.id}')  # a janela recebe a lista para a galeria

        # Na edição: a lixeira remove só a marcada e dá para somar novas.
        self.client.post(f'/programacao/itens/{item.id}/editar/', {'formato': 'reels',
            'titulo': 'Post lançamento', 'remover_midias': [str(reels.id)],
            'midias': [self._arquivo('nova.webp', 'image/webp')],
        })
        self.assertEqual([m.nome for m in item.midias.all()], ['capa.png', 'foto.jpg', 'nova.webp'])
        self.assertEqual(self.client.get(f'/programacao/midias/{reels.id}/').status_code, 404)

    def test_videos_grandes_sao_aceitos_e_ficam_em_disco(self):
        import os
        from unittest import mock
        from .models import ItemAgenda
        video = self._arquivo('IMG_3055.mov', 'video/quicktime', b'v' * (26 * 1024 * 1024))
        resp = self.client.post('/programacao/itens/', {'data': '2026-10-01', 'titulo': 'Reels', 'formato': 'reels',
                                                         'midias': [video]}, HTTP_X_REQUESTED_WITH='fetch')
        self.assertEqual(resp.status_code, 200)
        midia = ItemAgenda.objects.get(usuario=self.usuario).midias.get()
        self.assertEqual((midia.nome, midia.tamanho), ('IMG_3055.mov', 26 * 1024 * 1024))
        self.assertTrue(midia.arquivo.name.startswith('agenda/') and midia.arquivo.name.endswith('.mov'))
        caminho = midia.arquivo.path
        self.assertEqual(os.path.getsize(caminho), 26 * 1024 * 1024)

        # Entrega em blocos, também por partes (Range).
        parte = self.client.get(f'/programacao/midias/{midia.id}/', HTTP_RANGE='bytes=10-19')
        self.assertEqual((parte.status_code, b''.join(parte.streaming_content)), (206, b'v' * 10))
        inteiro = self.client.get(f'/programacao/midias/{midia.id}/')
        self.assertEqual(inteiro['Content-Length'], str(26 * 1024 * 1024))

        # Imagem continua limitada a 25 MB; vídeo acima do limite é recusado.
        imagem = self._arquivo('foto.png', 'image/png', b'i' * (26 * 1024 * 1024))
        resp = self.client.post('/programacao/itens/', {'data': '2026-10-01', 'titulo': 'x', 'formato': 'reels',
                                                         'midias': [imagem]}, HTTP_X_REQUESTED_WITH='fetch')
        self.assertEqual(resp.json(), {'erro': '“foto.png” tem mais de 25 MB. Envie uma versão menor.'})
        with mock.patch('core.agenda.LIMITE_VIDEO_MB', 1):
            resp = self.client.post('/programacao/itens/', {
                'data': '2026-10-01', 'titulo': 'x', 'formato': 'reels',
                'midias': [self._arquivo('longo.mp4', 'video/mp4', b'v' * (2 * 1024 * 1024))],
            }, HTTP_X_REQUESTED_WITH='fetch')
        self.assertEqual(resp.json(), {'erro': '“longo.mp4” tem mais de 1 MB. Envie uma versão menor.'})

        # Excluir o item apaga o arquivo do disco.
        item = ItemAgenda.objects.get(usuario=self.usuario)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f'/programacao/itens/{item.id}/excluir/')
        self.assertFalse(os.path.exists(caminho))

    def test_limite_de_midias_e_tipos_aceitos(self):
        from .models import ItemAgenda
        resp = self.client.post('/programacao/itens/', {
            'data': '2026-10-01', 'titulo': 'x', 'formato': 'reels', 'midias': [self._arquivo('a.pdf', 'application/pdf')],
        }, HTTP_X_REQUESTED_WITH='fetch')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('“a.pdf” não é aceito', resp.json()['erro'])

        onze = [self._arquivo(f'{i}.png', 'image/png') for i in range(11)]
        resp = self.client.post('/programacao/itens/', {'formato': 'reels', 'data': '2026-10-01', 'titulo': 'x', 'midias': onze},
                                HTTP_X_REQUESTED_WITH='fetch')
        self.assertEqual(resp.json(), {'erro': 'Cada item aceita até 10 imagens ou vídeos.'})
        self.assertFalse(ItemAgenda.objects.exists())

    def test_formato_e_obrigatorio_e_aparece_no_bloco(self):
        from .models import ItemAgenda
        resp = self.client.post('/programacao/itens/', {'data': '2026-10-01', 'titulo': 'Sem formato'},
                                HTTP_X_REQUESTED_WITH='fetch')
        self.assertEqual((resp.status_code, resp.json()),
                         (400, {'erro': 'Escolha o formato: Carrossel, Estático, Reels, Stories ou Outro.'}))
        self.client.post('/programacao/itens/', {'data': '2026-10-01', 'titulo': 'x', 'formato': 'tiktok'})
        self.assertFalse(ItemAgenda.objects.exists())

        self.client.post('/programacao/itens/', {'data': '2026-10-01', 'titulo': 'Bastidores', 'formato': 'stories'})
        item = ItemAgenda.objects.get(usuario=self.usuario)
        self.assertEqual(item.get_formato_display(), 'Stories')
        pagina = self.client.get('/programacao/', {'mes': '2026-10', 'dia': '2026-10-01'})
        self.assertContains(pagina, 'Stories</span>')
        self.assertContains(pagina, 'data-formato="stories"')
        self.assertContains(pagina, '<input type="radio" name="formato" value="carrossel" required>', html=True)

        # Editar também exige formato; sem ele nada muda.
        self.client.post(f'/programacao/itens/{item.id}/editar/', {'titulo': 'Outro título'})
        item.refresh_from_db()
        self.assertEqual((item.titulo, item.formato), ('Bastidores', 'stories'))
        self.client.post(f'/programacao/itens/{item.id}/editar/', {'titulo': 'Bastidores', 'formato': 'estatico'})
        item.refresh_from_db()
        self.assertEqual(item.get_formato_display(), 'Estático')

    def test_janela_envia_em_segundo_plano_e_recebe_json(self):
        from .models import ItemAgenda
        resp = self.client.post('/programacao/itens/', {'formato': 'reels', 'data': '2026-10-01', 'titulo': 'Reels'},
                                HTTP_X_REQUESTED_WITH='fetch')
        self.assertEqual(resp.json(), {'ok': True, 'url': '/programacao/?mes=2026-10&dia=2026-10-01'})
        item = ItemAgenda.objects.get(usuario=self.usuario)

        resp = self.client.post('/programacao/itens/', {'formato': 'reels', 'data': '2026-10-01', 'titulo': ' '}, HTTP_X_REQUESTED_WITH='fetch')
        self.assertEqual(resp.json(), {'erro': 'Preencha o título e o dia.'})

        resp = self.client.post(f'/programacao/itens/{item.id}/excluir/', HTTP_X_REQUESTED_WITH='fetch')
        self.assertEqual(resp.json()['url'], '/programacao/?mes=2026-10&dia=2026-10-01')
        self.assertFalse(ItemAgenda.objects.exists())

    def test_nao_mexe_em_item_de_outro_usuario(self):
        from .models import ItemAgenda, MidiaItemAgenda
        item = ItemAgenda.objects.create(usuario=self.outro, data=date(2026, 9, 24), titulo='Privado')
        midia = MidiaItemAgenda.objects.create(item=item, tipo='image/png', arquivo=self._arquivo('x.png', 'image/png'))
        self.assertEqual(self.client.get(f'/programacao/midias/{midia.id}/').status_code, 404)
        self.assertEqual(self.client.post(f'/programacao/itens/{item.id}/editar/', {'formato': 'reels', 'titulo': 'x'}).status_code, 404)
        self.assertEqual(self.client.post(f'/programacao/itens/{item.id}/concluir/').status_code, 404)
        self.assertEqual(self.client.post(f'/programacao/itens/{item.id}/excluir/').status_code, 404)
        self.assertNotContains(self.client.get('/programacao/', {'mes': '2026-09', 'dia': '2026-09-24'}), 'Privado')


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class QuadroTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.usuario = User.objects.create(username='quadro')
        self.outro = User.objects.create(username='outro')
        self.client.force_login(self.usuario)

    def _listas(self):
        from .models import ListaTarefas
        return list(ListaTarefas.objects.filter(usuario=self.usuario))

    def _titulos(self, lista):
        return list(lista.cartoes.values_list('titulo', flat=True))

    def test_primeiro_acesso_cria_colunas_padrao(self):
        resp = self.client.get('/tarefas/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([l.titulo for l in self._listas()], ['A fazer', 'Fazendo', 'Feito'])
        self.client.get('/tarefas/')
        self.assertEqual(len(self._listas()), 3)

    def test_prioridade_ordena_urgentes_medios_e_normais(self):
        from .models import Cartao
        self.client.get('/tarefas/')
        a_fazer = self._listas()[0]
        url = f'/tarefas/listas/{a_fazer.id}/cartoes/'
        self.client.post(url, {'titulo': 'Normal 1'})
        self.client.post(url, {'titulo': 'Urgente', 'prioridade': Cartao.URGENTE})
        self.client.post(url, {'titulo': 'Medio', 'prioridade': Cartao.MEDIO})
        self.client.post(url, {'titulo': 'Normal 2', 'prioridade': 'inventada'})
        self.assertEqual(self._titulos(a_fazer), ['Urgente', 'Medio', 'Normal 1', 'Normal 2'])

        pagina = self.client.get('/tarefas/')
        self.assertContains(pagina, '<span class="board-prio board-prio--urgente">Urgente</span>', html=True)
        self.assertContains(pagina, '<span class="board-prio board-prio--medio">Médio</span>', html=True)
        self.assertContains(pagina, '<span class="board-prio board-prio--normal">Normal</span>', count=2, html=True)

        # Mudar para urgente sobe o cartão; arrastar respeita a ordem dentro da mesma prioridade.
        normal2 = a_fazer.cartoes.get(titulo='Normal 2')
        self.client.post(f'/tarefas/cartoes/{normal2.id}/editar/',
                         {'titulo': 'Normal 2', 'prioridade': Cartao.URGENTE, 'lista': a_fazer.id})
        self.assertEqual(self._titulos(a_fazer), ['Urgente', 'Normal 2', 'Medio', 'Normal 1'])
        self.client.post(f'/tarefas/cartoes/{normal2.id}/mover/', {'lista': a_fazer.id, 'posicao': 0})
        self.assertEqual(self._titulos(a_fazer), ['Normal 2', 'Urgente', 'Medio', 'Normal 1'])

    def test_criar_e_mover_cartoes_mantendo_a_ordem(self):
        self.client.get('/tarefas/')
        a_fazer, fazendo, _ = self._listas()
        for titulo in ['Um', 'Dois', 'Tres']:
            resp = self.client.post(f'/tarefas/listas/{a_fazer.id}/cartoes/', {'titulo': titulo})
        self.assertRedirects(resp, f'/tarefas/#lista-{a_fazer.id}', fetch_redirect_response=False)
        self.assertEqual(self._titulos(a_fazer), ['Um', 'Dois', 'Tres'])

        tres = a_fazer.cartoes.get(titulo='Tres')
        resp = self.client.post(f'/tarefas/cartoes/{tres.id}/mover/', {'lista': a_fazer.id, 'posicao': 0},
                                HTTP_X_REQUESTED_WITH='fetch')
        self.assertEqual(resp.json(), {'ok': True})
        self.assertEqual(self._titulos(a_fazer), ['Tres', 'Um', 'Dois'])

        um = a_fazer.cartoes.get(titulo='Um')
        self.client.post(f'/tarefas/cartoes/{um.id}/mover/', {'lista': fazendo.id})
        self.assertEqual(self._titulos(a_fazer), ['Tres', 'Dois'])
        self.assertEqual(self._titulos(fazendo), ['Um'])

    def test_criar_renomear_e_excluir_coluna(self):
        from .models import Cartao
        self.client.get('/tarefas/')
        self.client.post('/tarefas/listas/', {'titulo': 'Ideias'})
        ideias = self._listas()[-1]
        self.assertEqual(ideias.titulo, 'Ideias')
        self.client.post(f'/tarefas/listas/{ideias.id}/editar/', {'titulo': 'Ideias de post'})
        ideias.refresh_from_db()
        self.assertEqual(ideias.titulo, 'Ideias de post')
        self.client.post(f'/tarefas/listas/{ideias.id}/cartoes/', {'titulo': 'Carrossel'})
        self.client.post(f'/tarefas/listas/{ideias.id}/excluir/')
        self.assertEqual(len(self._listas()), 3)
        self.assertFalse(Cartao.objects.filter(titulo='Carrossel').exists())

    def test_nao_mexe_no_quadro_de_outro_usuario(self):
        from .models import Cartao, ListaTarefas
        self.client.get('/tarefas/')
        minha = self._listas()[0]
        alheia = ListaTarefas.objects.create(usuario=self.outro, titulo='Deles')
        cartao_alheio = Cartao.objects.create(lista=alheia, titulo='Segredo')
        meu_cartao = Cartao.objects.create(lista=minha, titulo='Meu')

        self.assertEqual(self.client.post(f'/tarefas/listas/{alheia.id}/cartoes/', {'titulo': 'x'}).status_code, 404)
        self.assertEqual(self.client.post(f'/tarefas/listas/{alheia.id}/excluir/').status_code, 404)
        self.assertEqual(self.client.post(f'/tarefas/cartoes/{cartao_alheio.id}/excluir/').status_code, 404)
        self.assertEqual(self.client.post(f'/tarefas/cartoes/{cartao_alheio.id}/mover/', {'lista': minha.id}).status_code, 404)
        self.assertEqual(self.client.post(f'/tarefas/cartoes/{meu_cartao.id}/mover/', {'lista': alheia.id}).status_code, 404)
        self.assertEqual(self.client.post(f'/tarefas/cartoes/{meu_cartao.id}/mover/', {'lista': 'abc'}).status_code, 404)
        self.assertNotContains(self.client.get('/tarefas/'), 'Segredo')


class PaginacaoMidiasTests(SimpleTestCase):
    conexao = InstagramConnection(instagram_user_id='123', access_token='t')

    def test_busca_paginas_ate_ter_o_minimo_mesmo_com_periodo_curto(self):
        agora = timezone.now()

        def pagina(inicio, proxima):
            dados = [{'id': str(i), 'timestamp': (agora - timedelta(days=i)).strftime('%Y-%m-%dT%H:%M:%S+0000')}
                     for i in range(inicio, inicio + 25)]
            resp = mock.Mock(ok=True)
            resp.raise_for_status = lambda: None
            resp.json.return_value = {'data': dados, 'paging': {'next': proxima} if proxima else {}}
            return resp

        respostas = [pagina(0, 'p2'), pagina(25, 'p3'), pagina(50, 'p4')]
        with mock.patch('core.views.requests.get', side_effect=respostas) as get:
            midias, cobertas_desde = _buscar_midias_desde(self.conexao, agora - timedelta(days=2), minimo=50)
        self.assertEqual(len(midias), 50)
        self.assertEqual(get.call_count, 2)
        self.assertIsNone(cobertas_desde)


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class PublicoTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.usuario = User.objects.create(username='publico')
        self.client.force_login(self.usuario)

    def _conectar(self):
        InstagramConnection.objects.create(user=self.usuario, instagram_user_id='999', access_token='t')

    def _demografia(self, pares):
        return {'data': [{'name': 'follower_demographics', 'total_value': {'breakdowns': [{
            'dimension_keys': ['x'],
            'results': [{'dimension_values': [chave], 'value': valor} for chave, valor in pares],
        }]}}]}

    def _get(self, respostas_por_metrica):
        def responder(url, params=None, timeout=None):
            resp = mock.Mock(ok=True, status_code=200, text='')
            params = params or {}
            if url.endswith('/me'):
                resp.json.return_value = {'followers_count': 1000, 'profile_picture_url': ''}
                return resp
            chave = params.get('breakdown') or params.get('metric')
            ok, corpo = respostas_por_metrica.get(chave, (True, {}))
            resp.ok, resp.status_code = ok, 200 if ok else 400
            resp.json.return_value = corpo
            return resp

        with mock.patch('core.publico.requests.get', side_effect=responder), \
                mock.patch('core.views.requests.get', side_effect=responder):
            return self.client.get('/publico/dados/')

    def test_sem_conta_mostra_botao_de_conectar(self):
        resp = self.client.get('/publico/')
        self.assertContains(resp, 'Conectar com Instagram')

    def test_mostra_publico_com_porcentagens(self):
        self._conectar()
        horas = {str(h): (50 if h == 16 else 10) for h in range(24)}
        resp = self._get({
            'city': (True, self._demografia([('São Paulo, São Paulo', 300), ('Rio de Janeiro, Rio de Janeiro', 120)])),
            'country': (True, self._demografia([('BR', 900), ('PT', 60), ('ZZ', 5)])),
            'age': (True, self._demografia([('25-34', 500), ('18-24', 300), ('35-44', 200)])),
            'gender': (True, self._demografia([('F', 600), ('M', 380), ('U', 20)])),
            'online_followers': (True, {'data': [{'values': [{'value': horas}, {'value': horas}]}]}),
        })
        self.assertEqual(resp.status_code, 200)
        cidades = resp.context['cidades']['dados']
        self.assertEqual(cidades[0]['nome'], 'São Paulo, São Paulo')
        self.assertAlmostEqual(cidades[0]['percentual'], 30.0)
        paises = [p['nome'] for p in resp.context['paises']['dados']]
        self.assertEqual(paises, ['Brasil', 'Portugal', 'ZZ'])
        self.assertEqual([i['nome'] for i in resp.context['idades']['dados']][:3], ['13-17', '18-24', '25-34'])
        self.assertAlmostEqual(resp.context['idades']['dados'][2]['percentual'], 50.0)
        self.assertEqual([g['nome'] for g in resp.context['generos']['dados']], ['Feminino', 'Masculino', 'Não informado'])
        self.assertContains(resp, '30,0%')
        self.assertContains(resp, '60,0%')
        self.assertContains(resp, 'id="loc-cidades"')
        self.assertContains(resp, 'id="loc-paises" hidden')
        self.assertNotContains(resp, 'Principais cidades')
        horarios = resp.context['horarios']['dados']
        self.assertEqual(len(horarios['pontos']), 24)
        self.assertEqual(horarios['pico']['valor'], 50)
        self.assertTrue(horarios['linha'].startswith('M0.00,'))
        self.assertIn('Pico às', horarios['subtitulo'])
        self.assertContains(resp, 'class="linha-slot"', count=24)

        # Os três destaques do topo já dizem o que mais aparece.
        destaques = resp.context['destaques']
        self.assertEqual((destaques['genero']['nome'], destaques['genero']['chave']), ('Feminino', 'feminino'))
        self.assertEqual(destaques['idade']['nome'], '25 a 34 anos')
        self.assertEqual(destaques['local']['nome'], 'São Paulo')
        self.assertNotContains(resp, 'dos seguidores</p>')
        self.assertContains(resp, 'destaque-card destaque-card--feminino')
        self.assertContains(resp, '<p class="destaque-valor"><span class="destaque-rank">1º</span> São Paulo</p>', html=True)
        self.assertContains(resp, 'data-substitui="perfilTopo"')

    def test_conta_pequena_mostra_motivo_em_cada_bloco(self):
        self._conectar()
        recusa = (False, {'error': {'code': 100, 'message': 'Not enough users. Requires at least 100 followers'}})
        resp = self._get({'city': recusa, 'country': recusa, 'age': recusa, 'gender': recusa, 'online_followers': recusa})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'pelo menos 100 seguidores', count=5)
        self.assertEqual(resp.context['destaques'], {'genero': None, 'idade': None, 'local': None})
        self.assertContains(resp, 'destaque-card--vazio')

    def test_masculino_em_azul_e_pagina_abre_com_o_topo_do_perfil(self):
        self._conectar()
        resp = self._get({'gender': (True, self._demografia([('F', 100), ('M', 300), ('U', 900)]))})
        # "Não informado" não conta para o público favorito.
        self.assertEqual(resp.context['destaques']['genero']['chave'], 'masculino')
        pagina = self.client.get('/publico/')
        self.assertContains(pagina, 'id="perfilTopo"')
        self.assertNotContains(pagina, 'Seu público')
        self.assertNotContains(pagina, 'Retrato atual informado pelo Instagram')


class HorariosAtivosTests(SimpleTestCase):
    def test_converte_horario_do_pacifico_para_brasilia(self):
        from .publico import _medias_por_hora_local
        # 24/09/2026: Pacífico em horário de verão (UTC-7), Brasília UTC-3 → 4 horas de diferença.
        referencia = _local(2026, 9, 24, 12, 0)
        medias = _medias_por_hora_local([{'0': 10, '20': 40}, {'0': 20, '20': 60}], referencia)
        self.assertEqual(medias[4], 15)
        self.assertEqual(medias[0], 50)
        self.assertEqual(medias[1], 0)

    def test_no_inverno_do_hemisferio_norte_a_diferenca_e_5_horas(self):
        from .publico import _medias_por_hora_local
        referencia = _local(2026, 1, 15, 12, 0)
        self.assertEqual(_medias_por_hora_local([{'0': 7}], referencia)[5], 7)



@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class EsteiraDeProducaoTests(TestCase):
    PNG = b'\x89PNG\r\n\x1a\n' + b'0123456789' * 10

    def setUp(self):
        from django.contrib.auth.models import User
        self.usuario = User.objects.create(username='esteira')
        self.client.force_login(self.usuario)
        self.client.get('/tarefas/')
        from .models import ListaTarefas
        self.listas = list(ListaTarefas.objects.filter(usuario=self.usuario))

    def _arquivo(self, nome='foto.png', conteudo=None, tipo='image/png'):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(nome, conteudo if conteudo is not None else self.PNG, content_type=tipo)

    def test_cor_da_coluna_so_aceita_cores_da_paleta(self):
        lista = self.listas[0]
        self.client.post(f'/tarefas/listas/{lista.id}/editar/', {'titulo': lista.titulo, 'cor': '#3ddc84'})
        lista.refresh_from_db()
        self.assertEqual(lista.cor, '#3ddc84')
        self.client.post(f'/tarefas/listas/{lista.id}/editar/', {'titulo': lista.titulo, 'cor': 'red;}<script>'})
        lista.refresh_from_db()
        self.assertEqual(lista.cor, '#3ddc84')

    def test_mudar_ordem_das_colunas(self):
        from .models import ListaTarefas
        a_fazer = self.listas[0]
        resp = self.client.post(f'/tarefas/listas/{a_fazer.id}/mover/', {'posicao': 2}, HTTP_X_REQUESTED_WITH='fetch')
        self.assertEqual(resp.json(), {'ok': True})
        ordem = list(ListaTarefas.objects.filter(usuario=self.usuario).values_list('titulo', flat=True))
        self.assertEqual(ordem, ['Fazendo', 'Feito', 'A fazer'])
        self.client.post(f'/tarefas/listas/{a_fazer.id}/mover/', {'posicao': 0})
        ordem = list(ListaTarefas.objects.filter(usuario=self.usuario).values_list('titulo', flat=True))
        self.assertEqual(ordem, ['A fazer', 'Fazendo', 'Feito'])

    def test_cartao_com_legenda_e_imagem_e_servido_com_suporte_a_partes(self):
        from .models import Cartao
        lista = self.listas[0]
        self.client.post(f'/tarefas/listas/{lista.id}/cartoes/', {
            'titulo': 'Post de lançamento', 'legenda': 'Chegou! 🚀\nLink na bio.', 'arquivo': self._arquivo(),
        })
        cartao = Cartao.objects.get(titulo='Post de lançamento')
        self.assertEqual(cartao.legenda, 'Chegou! 🚀\nLink na bio.')
        self.assertTrue(cartao.e_imagem)
        self.assertEqual(cartao.midia_tamanho, len(self.PNG))

        resp = self.client.get(f'/tarefas/cartoes/{cartao.id}/arquivo/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'image/png')
        self.assertEqual(resp.content, self.PNG)

        resp = self.client.get(f'/tarefas/cartoes/{cartao.id}/arquivo/', HTTP_RANGE='bytes=0-7')
        self.assertEqual(resp.status_code, 206)
        self.assertEqual(resp['Content-Range'], f'bytes 0-7/{len(self.PNG)}')
        self.assertEqual(resp.content, self.PNG[:8])

        resp = self.client.get(f'/tarefas/cartoes/{cartao.id}/arquivo/', HTTP_RANGE='bytes=9999-')
        self.assertEqual(resp.status_code, 416)

        pagina = self.client.get('/tarefas/')
        self.assertContains(pagina, f'/tarefas/cartoes/{cartao.id}/arquivo/?v=1')

    def test_rejeita_tipo_nao_permitido_e_arquivo_grande(self):
        from .models import Cartao
        lista = self.listas[0]
        svg = self._arquivo('x.svg', b'<svg onload="alert(1)"/>', 'image/svg+xml')
        resp = self.client.post(f'/tarefas/listas/{lista.id}/cartoes/', {'titulo': 'SVG', 'arquivo': svg}, follow=True)
        self.assertContains(resp, 'Envie uma imagem')
        with mock.patch('core.quadro.LIMITE_MIDIA_MB', 0):
            resp = self.client.post(f'/tarefas/listas/{lista.id}/cartoes/', {'titulo': 'Grande', 'arquivo': self._arquivo()}, follow=True)
        self.assertContains(resp, 'Envie uma versão menor')
        self.assertFalse(Cartao.objects.exists())

    def test_editar_cartao_troca_coluna_e_remove_midia(self):
        from .models import ArquivoCartao, Cartao
        a_fazer, fazendo, _ = self.listas
        self.client.post(f'/tarefas/listas/{a_fazer.id}/cartoes/', {'titulo': 'Reels', 'arquivo': self._arquivo('v.mp4', b'mp4', 'video/mp4')})
        cartao = Cartao.objects.get(titulo='Reels')
        self.assertTrue(cartao.e_video)

        self.client.post(f'/tarefas/cartoes/{cartao.id}/editar/', {
            'titulo': 'Reels editado', 'legenda': 'Nova legenda', 'lista': fazendo.id, 'remover_midia': '1',
        })
        cartao.refresh_from_db()
        self.assertEqual((cartao.titulo, cartao.legenda, cartao.lista_id), ('Reels editado', 'Nova legenda', fazendo.id))
        self.assertEqual(cartao.midia_tipo, '')
        self.assertFalse(ArquivoCartao.objects.exists())
        self.assertEqual(self.client.get(f'/tarefas/cartoes/{cartao.id}/arquivo/').status_code, 404)

    def test_nao_acessa_midia_nem_edita_cartao_de_outro_usuario(self):
        from django.contrib.auth.models import User
        from .models import ArquivoCartao, Cartao, ListaTarefas
        outro = User.objects.create(username='intruso')
        lista = ListaTarefas.objects.create(usuario=outro, titulo='Deles')
        cartao = Cartao.objects.create(lista=lista, titulo='Segredo', midia_tipo='image/png')
        ArquivoCartao.objects.create(cartao=cartao, conteudo=self.PNG)

        self.assertEqual(self.client.get(f'/tarefas/cartoes/{cartao.id}/arquivo/').status_code, 404)
        self.assertEqual(self.client.post(f'/tarefas/cartoes/{cartao.id}/editar/', {'titulo': 'x'}).status_code, 404)
        self.assertEqual(self.client.post(f'/tarefas/listas/{lista.id}/mover/', {'posicao': 0}).status_code, 404)
        self.assertEqual(self.client.post(f'/tarefas/listas/{lista.id}/editar/', {'cor': '#3ddc84'}).status_code, 404)
        cartao.refresh_from_db()
        self.assertEqual(cartao.titulo, 'Segredo')


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class UsuariosEPermissoesTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.admin = User.objects.get(username='mironlucas')
        self.client.force_login(self.admin)

    def _criar(self, usuario, papel, senha='Nexora#2026x'):
        return self.client.post('/usuarios/', {'nome': usuario.title(), 'usuario': usuario, 'senha': senha, 'papel': papel})

    def _entrar_como(self, usuario):
        from django.contrib.auth.models import User
        self.client.force_login(User.objects.get(username=usuario))

    def test_admin_inicial_tem_perfil_de_administrador(self):
        self.assertEqual(self.admin.perfis.get().papel, 'admin')
        self.assertEqual(self.admin.perfis.get().conta, self.admin)
        self.assertContains(self.client.get('/dashboard/'), 'href="/usuarios/"')

    def test_admin_cria_usuarios_na_propria_conta(self):
        from django.contrib.auth.models import User
        resp = self._criar('ana', 'editor')
        self.assertRedirects(resp, '/usuarios/', fetch_redirect_response=False)
        ana = User.objects.get(username='ana')
        self.assertEqual((ana.perfis.get().papel, ana.perfis.get().conta), ('editor', self.admin))
        self.assertTrue(ana.check_password('Nexora#2026x'))
        self.assertContains(self.client.get('/usuarios/'), '@ana')

    def test_senha_fraca_usuario_repetido_e_papel_invalido_sao_recusados(self):
        from django.contrib.auth.models import User
        resp = self._criar('bia', 'editor', senha='12345678')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['form'].errors['senha'])
        resp = self._criar('MironLucas', 'editor')
        self.assertIn('Essa pessoa já tem acesso a esta conta.', resp.context['form'].errors['usuario'])
        resp = self._criar('caio', 'admin')
        self.assertTrue(resp.context['form'].errors['papel'])
        self.assertFalse(User.objects.filter(username__in=['bia', 'caio']).exists())

    def test_editor_altera_dados_compartilhados_mas_nao_acessa_usuarios(self):
        from .models import Cartao, ItemAgenda, ListaTarefas
        self.client.get('/tarefas/')
        lista = ListaTarefas.objects.filter(usuario=self.admin).first()
        self._criar('ana', 'editor')
        self._entrar_como('ana')

        self.client.post(f'/tarefas/listas/{lista.id}/cartoes/', {'titulo': 'Feito pela Ana'})
        self.client.post('/programacao/itens/', {'data': '2026-09-24', 'titulo': 'Reunião', 'formato': 'outro'})
        self.assertTrue(Cartao.objects.filter(lista=lista, titulo='Feito pela Ana').exists())
        self.assertTrue(ItemAgenda.objects.filter(usuario=self.admin, titulo='Reunião').exists())
        self.assertEqual(ListaTarefas.objects.filter(usuario__username='ana').count(), 0)

        self.assertEqual(self.client.get('/usuarios/').status_code, 403)
        self.assertEqual(self._criar('intruso', 'editor').status_code, 403)
        self.assertNotContains(self.client.get('/dashboard/'), 'href="/usuarios/"')

    def test_visualizacao_nao_altera_nada(self):
        from .models import Cartao, ItemAgenda, ListaTarefas
        self.client.get('/tarefas/')
        lista = ListaTarefas.objects.filter(usuario=self.admin).first()
        cartao = Cartao.objects.create(lista=lista, titulo='Original')
        ItemAgenda.objects.create(usuario=self.admin, data=date(2026, 9, 24), titulo='Item')
        self._criar('vini', 'visualizador')
        self._entrar_como('vini')

        for pagina in ['/dashboard/', '/publico/', '/programacao/', '/tarefas/']:
            self.assertEqual(self.client.get(pagina).status_code, 200, pagina)

        resp = self.client.post('/programacao/itens/', {'data': '2026-09-24', 'titulo': 'Novo'}, follow=True)
        self.assertContains(resp, 'Seu acesso é somente de visualização.')
        self.client.post(f'/tarefas/cartoes/{cartao.id}/editar/', {'titulo': 'Alterado'})
        self.client.post(f'/tarefas/cartoes/{cartao.id}/excluir/')
        self.client.post(f'/tarefas/listas/{lista.id}/editar/', {'cor': '#3ddc84'})
        self.client.post('/instagram/conectar/')
        resp = self.client.post(f'/tarefas/cartoes/{cartao.id}/mover/', {'lista': lista.id}, HTTP_X_REQUESTED_WITH='fetch')
        self.assertEqual(resp.status_code, 403)

        cartao.refresh_from_db()
        lista.refresh_from_db()
        self.assertEqual(cartao.titulo, 'Original')
        self.assertEqual(lista.cor, '#7c5cff')
        self.assertEqual(ItemAgenda.objects.count(), 1)
        self.assertEqual(self.client.get('/usuarios/').status_code, 403)

    def test_visualizacao_nao_ve_botoes_de_edicao(self):
        self.client.get('/tarefas/')
        self._criar('vini', 'visualizador')
        self._entrar_como('vini')
        tarefas = self.client.get('/tarefas/')
        self.assertNotContains(tarefas, 'class="board-add-btn')
        self.assertNotContains(tarefas, 'class="board-grip"')
        self.assertNotContains(tarefas, 'js-config-lista"')
        self.assertNotContains(tarefas, 'placeholder="+ Nova coluna"')
        self.assertNotContains(self.client.get('/dashboard/'), 'Conectar com Instagram')
        self.assertContains(self.client.get('/dashboard/'), 'Visualização')

    def test_visualizacao_abre_o_item_da_programacao_so_para_ver(self):
        from .models import ItemAgenda
        ItemAgenda.objects.create(usuario=self.admin, data=date(2026, 10, 1), titulo='Reels', formato='reels')
        self._criar('vini', 'visualizador')
        self._entrar_como('vini')
        pagina = self.client.get('/programacao/', {'mes': '2026-10', 'dia': '2026-10-01'})
        self.assertContains(pagina, 'class="day-item-body js-abrir-item" title="Ver detalhes"')
        self.assertContains(pagina, 'data-formato="reels"')
        self.assertContains(pagina, 'id="dialogItem"')
        self.assertContains(pagina, '<input type="radio" name="formato" value="reels" required disabled>', html=True)
        self.assertContains(pagina, 'placeholder="Sem legenda" readonly')
        for so_de_quem_edita in ('data-editar=', 'id="novoItem"', 'id="itemSalvar"', 'id="itemExcluir"', 'id="itemAdicionarMidias"'):
            self.assertNotContains(pagina, so_de_quem_edita)

    def test_admin_nao_edita_a_si_mesmo_nem_membro_de_outra_conta(self):
        from django.contrib.auth.models import User
        from .models import Perfil
        self.assertEqual(self.client.post(f'/usuarios/{self.admin.perfis.get().id}/excluir/').status_code, 404)
        outro_admin = User.objects.create_user('outro', password='x')
        estranho = User.objects.create_user('estranho', password='x')
        perfil_estranho = Perfil.objects.create(usuario=estranho, conta=outro_admin, papel='editor')
        self.assertEqual(self.client.post(f'/usuarios/{perfil_estranho.id}/excluir/').status_code, 404)
        self.assertTrue(User.objects.filter(username='estranho').exists())

    def test_admin_muda_acesso_senha_e_exclui_usuario(self):
        from django.contrib.auth.models import User
        self._criar('ana', 'editor')
        ana = User.objects.get(username='ana')
        self.client.post(f'/usuarios/{ana.perfis.get().id}/editar/', {'nome': 'Ana Souza', 'papel': 'visualizador', 'senha': 'OutraSenha#99'})
        ana.refresh_from_db()
        self.assertEqual((ana.first_name, ana.perfis.get().papel), ('Ana Souza', 'visualizador'))
        self.assertTrue(ana.check_password('OutraSenha#99'))
        self.client.post(f'/usuarios/{ana.perfis.get().id}/excluir/')
        self.assertFalse(User.objects.filter(username='ana').exists())

    def test_conectar_instagram_nao_mostra_mais_mensagem_de_sucesso(self):
        session = self.client.session
        session['instagram_oauth_state'] = 'abc'
        session.save()
        with mock.patch('core.views._trocar_code_por_token_curto', return_value={'access_token': 'c'}), \
                mock.patch('core.views._trocar_token_curto_por_longo', return_value={'access_token': 'l', 'expires_in': 100}), \
                mock.patch('core.views._buscar_perfil', return_value={'id': '1', 'username': 'nathaliaalexandree'}), \
                mock.patch('core.views._dados_do_dashboard', return_value={}):
            resp = self.client.get('/instagram/callback/', {'code': 'x', 'state': 'abc'}, follow=True)
        self.assertNotContains(resp, 'conectada com sucesso')
        self.assertEqual(self.admin.instagram_connection.instagram_username, 'nathaliaalexandree')


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class FalhaCsrfTests(TestCase):
    def setUp(self):
        from django.test import Client
        self.client = Client(enforce_csrf_checks=True)

    def test_login_com_pagina_desatualizada_volta_para_o_login(self):
        resp = self.client.post('/', {'username': 'mironlucas', 'password': 'x', 'next': '/tarefas/'})
        self.assertRedirects(resp, '/?expirou=1&next=/tarefas/', fetch_redirect_response=False)
        pagina = self.client.get(resp['Location'])
        self.assertContains(pagina, 'estava desatualizada')
        self.assertContains(pagina, 'placeholder="Digite seu usuário"')

    def test_formulario_desatualizado_volta_com_aviso_e_nao_salva(self):
        from django.contrib.auth.models import User
        from .models import ItemAgenda
        self.client.force_login(User.objects.get(username='mironlucas'))
        resp = self.client.post('/programacao/itens/', {'titulo': 'x', 'data': '2026-09-25'},
                                HTTP_REFERER='http://testserver/programacao/')
        self.assertRedirects(resp, 'http://testserver/programacao/', fetch_redirect_response=False)
        self.assertFalse(ItemAgenda.objects.exists())

    def test_fetch_desatualizado_recebe_json(self):
        from django.contrib.auth.models import User
        self.client.force_login(User.objects.get(username='mironlucas'))
        resp = self.client.post('/tarefas/listas/', HTTP_X_REQUESTED_WITH='fetch')
        self.assertEqual(resp.status_code, 403)
        self.assertIn('desatualizada', resp.json()['erro'])

    def test_quem_ja_entrou_nao_ve_o_login_de_novo(self):
        from django.contrib.auth.models import User
        self.client.force_login(User.objects.get(username='mironlucas'))
        self.assertRedirects(self.client.get('/'), '/dashboard/', fetch_redirect_response=False)


def _signed_request(dados, segredo='segredo-do-app'):
    import base64
    import hashlib
    import hmac
    import json

    def b64(valor):
        return base64.urlsafe_b64encode(valor).rstrip(b'=').decode()

    conteudo = b64(json.dumps(dados).encode())
    assinatura = b64(hmac.new(segredo.encode(), conteudo.encode(), hashlib.sha256).digest())
    return f'{assinatura}.{conteudo}'


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage',
                   INSTAGRAM_CLIENT_SECRET='segredo-do-app', CONTATO_EMAIL='contato@nextsora.tech')
class PaginasDaMetaTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.dono = User.objects.get(username='mironlucas')
        InstagramConnection.objects.create(user=self.dono, instagram_user_id='111', instagram_conta_id='222', access_token='t')
        SeguidoresDia.objects.create(instagram_user_id='111', data=date(2026, 9, 1), novos_seguidores=5)

    def test_paginas_publicas_abrem_sem_login(self):
        for url, texto in [('/privacidade/', 'Política de Privacidade'), ('/termos/', 'Termos de Uso'),
                           ('/exclusao-de-dados/', 'Exclusão de dados')]:
            resp = self.client.get(url)
            self.assertContains(resp, texto)
            self.assertContains(resp, 'mailto:contato@nextsora.tech')
        login = self.client.get('/')
        self.assertContains(login, 'href="/privacidade/"')

    def test_remover_o_app_apaga_o_acesso_mas_mantem_o_historico(self):
        resp = self.client.post('/instagram/desautorizar/', {'signed_request': _signed_request(
            {'algorithm': 'HMAC-SHA256', 'user_id': '222'})})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(InstagramConnection.objects.exists())
        self.assertTrue(SeguidoresDia.objects.exists())

    def test_assinatura_invalida_e_recusada(self):
        for rota in ('/instagram/desautorizar/', '/instagram/exclusao/'):
            resp = self.client.post(rota, {'signed_request': _signed_request(
                {'algorithm': 'HMAC-SHA256', 'user_id': '111'}, segredo='outro')})
            self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.client.post('/instagram/exclusao/', {'signed_request': 'lixo'}).status_code, 400)
        self.assertEqual(self.client.get('/instagram/exclusao/').status_code, 405)
        self.assertTrue(InstagramConnection.objects.exists())

    def test_exclusao_apaga_tudo_e_devolve_codigo_para_acompanhar(self):
        from .models import SolicitacaoExclusao
        resp = self.client.post('/instagram/exclusao/', {'signed_request': _signed_request(
            {'algorithm': 'HMAC-SHA256', 'user_id': '222'})}, secure=True)
        corpo = resp.json()
        codigo = corpo['confirmation_code']
        self.assertEqual(corpo['url'], f'https://testserver/exclusao-de-dados/?codigo={codigo}')
        self.assertFalse(InstagramConnection.objects.exists())
        self.assertFalse(SeguidoresDia.objects.exists())
        self.assertTrue(SolicitacaoExclusao.objects.filter(codigo=codigo, concluida_em__isnull=False).exists())
        self.assertContains(self.client.get('/exclusao-de-dados/', {'codigo': codigo}), 'concluída')
        self.assertContains(self.client.get('/exclusao-de-dados/', {'codigo': 'nao-existe'}), 'não encontrado')


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class PaineisSeparadosTests(TestCase):
    def test_criar_painel_cria_admin_dono_da_propria_conta(self):
        from django.contrib.auth.models import User
        from django.core.management import call_command
        with mock.patch('core.management.commands.criar_painel.getpass.getpass', return_value='Painel#Novo2026'):
            call_command('criar_painel', 'mironlucas2', stdout=mock.Mock())
        novo = User.objects.get(username='mironlucas2')
        self.assertTrue(novo.check_password('Painel#Novo2026'))
        self.assertEqual((novo.perfis.get().conta, novo.perfis.get().papel), (novo, 'admin'))

    def test_um_painel_nao_ve_os_dados_do_outro(self):
        from django.contrib.auth.models import User
        from .models import ItemAgenda, ListaTarefas, Perfil
        primeiro = User.objects.get(username='mironlucas')
        segundo = User.objects.create_user('mironlucas2', password='x')
        Perfil.objects.create(usuario=segundo, conta=segundo, papel=Perfil.ADMIN)
        InstagramConnection.objects.create(user=primeiro, instagram_user_id='1', instagram_username='conta_um', access_token='t')
        item = ItemAgenda.objects.create(usuario=primeiro, data=date(2026, 10, 1), titulo='Programação do painel 1')
        self.client.force_login(primeiro)
        self.client.get('/tarefas/')
        lista = ListaTarefas.objects.filter(usuario=primeiro).first()

        self.client.force_login(segundo)
        self.assertContains(self.client.get('/dashboard/'), 'Conectar com Instagram')
        self.assertNotContains(self.client.get('/programacao/', {'mes': '2026-10', 'dia': '2026-10-01'}),
                               'Programação do painel 1')
        self.assertEqual(self.client.post(f'/programacao/itens/{item.id}/excluir/').status_code, 404)
        self.assertEqual(self.client.post(f'/tarefas/listas/{lista.id}/excluir/').status_code, 404)
        self.assertNotContains(self.client.get('/usuarios/'), '@mironlucas<')

        # Quem o segundo painel cadastra em Usuários entra no segundo painel.
        self.client.post('/usuarios/', {'nome': 'Bia', 'usuario': 'bia', 'senha': 'Senha#Forte2026', 'papel': 'editor'})
        self.assertEqual(User.objects.get(username='bia').perfis.get().conta, segundo)


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage',
                   INSTAGRAM_CLIENT_ID='app', INSTAGRAM_CLIENT_SECRET='segredo',
                   INSTAGRAM_REDIRECT_URI='https://testserver/instagram/callback/')
class VariasContasTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.pessoa = User.objects.get(username='mironlucas')
        InstagramConnection.objects.create(user=self.pessoa, instagram_user_id='1', instagram_username='conta_um',
                                           access_token='t')
        self.client.force_login(self.pessoa)

    def _adicionar(self, instagram_id, username, nova=True):
        self.client.get('/instagram/conectar/', {'nova': '1'} if nova else {})
        state = self.client.session['instagram_oauth_state']
        with mock.patch('core.views._trocar_code_por_token_curto', return_value={'access_token': 'c'}), \
                mock.patch('core.views._trocar_token_curto_por_longo', return_value={'access_token': 'novo', 'expires_in': 100}), \
                mock.patch('core.views._buscar_perfil', return_value={'id': instagram_id, 'username': username}):
            return self.client.get('/instagram/callback/', {'code': 'x', 'state': state})

    def _outra_pessoa(self, usuario='outra'):
        from django.contrib.auth.models import User
        from .models import Perfil
        outra = User.objects.create_user(usuario, password='x')
        Perfil.objects.create(usuario=outra, conta=outra, papel=Perfil.ADMIN)
        return outra

    def test_adicionar_conta_cria_conta_nova_administrada_por_quem_adicionou_e_abre_ela(self):
        from .models import Perfil
        resp = self._adicionar('2', 'conta_dois')
        self.assertRedirects(resp, '/dashboard/', fetch_redirect_response=False)
        conexao = InstagramConnection.objects.get(instagram_user_id='2')
        self.assertNotEqual(conexao.user, self.pessoa)
        self.assertFalse(conexao.user.is_active)
        self.assertFalse(conexao.user.has_usable_password())
        self.assertEqual(Perfil.objects.get(usuario=self.pessoa, conta=conexao.user).papel, Perfil.ADMIN)
        self.assertEqual(self.client.session['conta_atual'], conexao.user.id)
        # A conta antiga continua igual, com os mesmos dados.
        self.assertEqual(InstagramConnection.objects.get(user=self.pessoa).instagram_username, 'conta_um')

        pagina = self.client.get('/programacao/')
        self.assertContains(pagina, '<span class="account-handle">@conta_dois</span>', html=True)
        self.assertContains(pagina, '@conta_um')
        self.assertContains(pagina, 'Adicionar conta')

    def test_dados_ficam_separados_por_conta_e_troca_pelo_menu(self):
        from .models import ItemAgenda
        ItemAgenda.objects.create(usuario=self.pessoa, data=date(2026, 10, 1), titulo='Post da conta um')
        self._adicionar('2', 'conta_dois')
        nova = InstagramConnection.objects.get(instagram_user_id='2').user
        filtro = {'mes': '2026-10', 'dia': '2026-10-01'}
        self.assertNotContains(self.client.get('/programacao/', filtro), 'Post da conta um')

        resp = self.client.post(f'/contas/{self.pessoa.id}/usar/', HTTP_REFERER='http://testserver/programacao/')
        self.assertRedirects(resp, 'http://testserver/programacao/', fetch_redirect_response=False)
        self.assertContains(self.client.get('/programacao/', filtro), 'Post da conta um')
        self.client.post(f'/contas/{nova.id}/usar/')
        self.assertNotContains(self.client.get('/programacao/', filtro), 'Post da conta um')

    def test_instagram_de_outro_administrador_retorna_erro(self):
        outra = self._outra_pessoa()
        InstagramConnection.objects.create(user=outra, instagram_user_id='9', instagram_username='da_outra',
                                           access_token='deles')
        resp = self._adicionar('9', 'da_outra')
        self.assertRedirects(resp, '/dashboard/', fetch_redirect_response=False)
        mensagens = [str(m) for m in resp.wsgi_request._messages]
        self.assertIn('Esta conta já está conectada por um usuário. Entre em contato com o administrador da conta '
                      'ou com o nosso suporte.', mensagens)
        self.assertEqual(InstagramConnection.objects.get(instagram_user_id='9').access_token, 'deles')
        self.assertEqual(InstagramConnection.objects.count(), 2)
        # Nem conectando na conta aberta dá para tomar o Instagram de outra conta.
        self._adicionar('9', 'da_outra', nova=False)
        self.assertEqual(InstagramConnection.objects.get(user=self.pessoa).instagram_username, 'conta_um')

    def test_instagram_que_ja_esta_no_painel_so_abre_a_conta(self):
        self._adicionar('2', 'conta_dois')
        self.client.post(f'/contas/{self.pessoa.id}/usar/')
        resp = self._adicionar('2', 'conta_dois')
        conexao = InstagramConnection.objects.get(instagram_user_id='2')
        self.assertIn('@conta_dois já está no seu painel.', [str(m) for m in resp.wsgi_request._messages])
        self.assertEqual(self.client.session['conta_atual'], conexao.user_id)
        self.assertEqual(InstagramConnection.objects.count(), 2)

    def test_nao_abre_nem_desconecta_conta_de_outra_pessoa(self):
        outra = self._outra_pessoa()
        InstagramConnection.objects.create(user=outra, instagram_user_id='9', instagram_username='da_outra', access_token='t')
        self.assertEqual(self.client.post(f'/contas/{outra.id}/usar/').status_code, 404)
        self.assertEqual(self.client.post(f'/contas/{outra.id}/desconectar/').status_code, 404)
        self.assertTrue(InstagramConnection.objects.filter(user=outra).exists())
        self.assertEqual(self.client.get(f'/contas/{self.pessoa.id}/usar/').status_code, 405)

    def test_convidado_visualiza_troca_de_conta_e_adiciona_a_propria_mas_nao_desconecta(self):
        from .models import Perfil
        convidada = self._outra_pessoa('convidada')
        Perfil.objects.create(usuario=convidada, conta=self.pessoa, papel=Perfil.VISUALIZADOR)
        self.client.force_login(convidada)
        self.client.post(f'/contas/{self.pessoa.id}/usar/')
        self.assertEqual(self.client.session['conta_atual'], self.pessoa.id)
        menu = self.client.get('/dashboard/')
        self.assertContains(menu, 'Convidado')
        self.assertNotContains(menu, f'/contas/{self.pessoa.id}/desconectar/')
        self.assertEqual(self.client.post(f'/contas/{self.pessoa.id}/desconectar/').status_code, 404)
        self.assertTrue(InstagramConnection.objects.filter(user=self.pessoa).exists())

        # Só de visualização aqui, mas pode adicionar um Instagram dela, que vira uma conta que ela administra.
        self._adicionar('5', 'dela')
        nova = InstagramConnection.objects.get(instagram_user_id='5').user
        self.assertEqual(Perfil.objects.get(usuario=convidada, conta=nova).papel, Perfil.ADMIN)
        self.assertEqual(InstagramConnection.objects.get(user=self.pessoa).instagram_username, 'conta_um')

    def test_desconectar_tira_a_conta_da_lista_e_adicionar_de_novo_traz_os_dados(self):
        from .models import ItemAgenda
        self._adicionar('2', 'conta_dois')
        nova = InstagramConnection.objects.get(instagram_user_id='2').user
        ItemAgenda.objects.create(usuario=nova, data=date(2026, 10, 1), titulo='Post da conta dois')
        self.assertContains(self.client.get('/dashboard/'), f'/contas/{nova.id}/desconectar/')

        self.client.post(f'/contas/{nova.id}/desconectar/')
        self.assertFalse(InstagramConnection.objects.filter(user=nova).exists())
        self.assertTrue(ItemAgenda.objects.filter(usuario=nova).exists())
        self.assertContains(self.client.get('/dashboard/'), 'foi desconectada e saiu da sua lista de contas')
        pagina = self.client.get('/programacao/', {'mes': '2026-10', 'dia': '2026-10-01'})
        self.assertNotContains(pagina, 'conta_dois')
        self.assertNotContains(pagina, 'Post da conta dois')
        # A conta aberta passa a ser uma que ainda tem Instagram.
        self.assertContains(pagina, '<span class="account-handle">@conta_um</span>', html=True)
        self.assertEqual(self.client.post(f'/contas/{nova.id}/desconectar/').status_code, 302)

        resp = self._adicionar('2', 'conta_dois')
        self.assertEqual(InstagramConnection.objects.get(instagram_user_id='2').user, nova)
        self.assertIn('@conta_dois voltou para a sua lista de contas, com a programação e as tarefas de antes.',
                      [str(m) for m in resp.wsgi_request._messages])
        self.assertContains(self.client.get('/programacao/', {'mes': '2026-10', 'dia': '2026-10-01'}), 'Post da conta dois')

    def test_desconectar_a_conta_principal_e_adicionar_de_novo_volta_para_ela(self):
        from .models import ItemAgenda
        ItemAgenda.objects.create(usuario=self.pessoa, data=date(2026, 10, 1), titulo='Post da conta um')
        self._adicionar('2', 'conta_dois')
        self.client.post(f'/contas/{self.pessoa.id}/desconectar/', follow=True)
        self.assertNotContains(self.client.get('/dashboard/'), 'conta_um')
        self._adicionar('1', 'conta_um')
        self.assertEqual(InstagramConnection.objects.get(instagram_user_id='1').user, self.pessoa)
        self.assertContains(self.client.get('/programacao/', {'mes': '2026-10', 'dia': '2026-10-01'}), 'Post da conta um')

    def test_so_a_ultima_conta_desconectada_continua_aberta_para_conectar_de_novo(self):
        self.client.post(f'/contas/{self.pessoa.id}/desconectar/')
        pagina = self.client.get('/dashboard/')
        self.assertContains(pagina, 'Instagram desconectado')
        self.assertContains(pagina, 'Conectar com Instagram')
        self.assertNotContains(pagina, 'Suas contas')
        self.assertContains(pagina, 'Adicionar conta')
        # Conectar de novo pelo botão do dashboard volta para a mesma conta.
        self._adicionar('1', 'conta_um', nova=False)
        self.assertEqual(InstagramConnection.objects.get(instagram_user_id='1').user, self.pessoa)

    def test_primeiro_instagram_vai_para_a_propria_conta_e_outro_nunca_substitui(self):
        outra = self._outra_pessoa()
        self.client.force_login(outra)
        self._adicionar('7', 'primeiro')
        self.assertEqual(InstagramConnection.objects.get(instagram_user_id='7').user, outra)
        # Pelo botão sem "nova", um Instagram diferente também vira conta nova em vez de trocar o atual.
        self._adicionar('8', 'segundo', nova=False)
        self.assertEqual(InstagramConnection.objects.get(user=outra).instagram_user_id, '7')
        self.assertNotEqual(InstagramConnection.objects.get(instagram_user_id='8').user, outra)

    def test_exclusao_pela_meta_esquece_o_instagram_desconectado(self):
        from .models import InstagramAnterior
        self.client.post(f'/contas/{self.pessoa.id}/desconectar/')
        self.assertTrue(InstagramAnterior.objects.filter(conta=self.pessoa, instagram_user_id='1').exists())
        from . import meta
        with mock.patch.object(meta, '_ler_signed_request', return_value={'user_id': '1'}):
            self.client.post('/instagram/exclusao/', {'signed_request': 'x.y'})
        self.assertFalse(InstagramAnterior.objects.exists())

    def test_convidar_quem_ja_tem_login_e_proteger_a_senha_dele(self):
        from django.contrib.auth.models import User
        from .models import Perfil
        outra = self._outra_pessoa('mironlucas2')
        resp = self.client.post('/usuarios/', {'nome': '', 'usuario': 'mironlucas2', 'senha': '', 'papel': 'visualizador'})
        self.assertRedirects(resp, '/usuarios/', fetch_redirect_response=False)
        acesso = Perfil.objects.get(usuario=outra, conta=self.pessoa)
        self.assertEqual(acesso.papel, 'visualizador')
        self.assertTrue(outra.check_password('x'))
        self.assertContains(self.client.get('/usuarios/'), 'data-compartilhado="1"')

        # Quem a convidou muda o acesso, mas não a senha nem o nome (ela tem outra conta).
        self.client.post(f'/usuarios/{acesso.id}/editar/', {'nome': 'Trocado', 'papel': 'editor', 'senha': 'Invasao#2026x'})
        outra.refresh_from_db()
        acesso.refresh_from_db()
        self.assertEqual(acesso.papel, 'editor')
        self.assertTrue(outra.check_password('x'))
        self.assertEqual(outra.first_name, '')

        # Remover tira só o acesso a esta conta; o login dela continua.
        self.client.post(f'/usuarios/{acesso.id}/excluir/')
        self.assertFalse(Perfil.objects.filter(usuario=outra, conta=self.pessoa).exists())
        self.assertTrue(User.objects.filter(username='mironlucas2').exists())

        resp = self.client.post('/usuarios/', {'usuario': 'mironlucas', 'senha': '', 'papel': 'editor'})
        self.assertIn('Essa pessoa já tem acesso a esta conta.', resp.context['form'].errors['usuario'])
        conta_oculta = InstagramConnection.objects.get(user=self.pessoa)  # contas adicionadas não são logins
        self._adicionar('2', 'conta_dois')
        oculta = InstagramConnection.objects.get(instagram_user_id='2').user.username
        self.client.post(f'/contas/{conta_oculta.user_id}/usar/')
        resp = self.client.post('/usuarios/', {'usuario': oculta, 'senha': '', 'papel': 'editor'})
        self.assertIn('Esse nome de usuário não está disponível.', resp.context['form'].errors['usuario'])


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class ComentariosItemTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        from .models import ItemAgenda, Perfil
        self.admin = User.objects.get(username='mironlucas')
        self.admin.first_name = 'Miron'
        self.admin.save()
        self.cliente = User.objects.create_user('cliente', password='x', first_name='Cliente')
        Perfil.objects.create(usuario=self.cliente, conta=self.admin, papel=Perfil.VISUALIZADOR)
        self.item = ItemAgenda.objects.create(usuario=self.admin, data=date(2026, 10, 1), titulo='Post de outubro',
                                              formato='reels')
        self.url = f'/programacao/itens/{self.item.id}/comentarios/'
        self.client.force_login(self.admin)

    def test_quem_cria_e_quem_so_visualiza_conversam_no_item(self):
        resp = self.client.post(self.url, {'texto': '  Subi a arte e a legenda.  '})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['comentario']['texto'], 'Subi a arte e a legenda.')

        self.client.force_login(self.cliente)
        self.client.get('/dashboard/')
        resp = self.client.post(self.url, {'texto': 'Troca a cor do título\npor favor'})
        self.assertEqual(resp.status_code, 201)

        comentarios = self.client.get(self.url).json()['comentarios']
        self.assertEqual([(c['autor'], c['texto'], c['meu']) for c in comentarios], [
            ('Miron', 'Subi a arte e a legenda.', False),
            ('Cliente', 'Troca a cor do título\npor favor', True),
        ])
        self.assertRegex(comentarios[0]['quando'], r'^(Hoje|Ontem|\d\d/\d\d(/\d{4})?) às \d\d:\d\d$')
        self.assertEqual(comentarios[0]['excluir'], '')
        self.assertTrue(comentarios[1]['excluir'])
        # Quem só visualiza continua sem poder editar o item.
        self.client.post(f'/programacao/itens/{self.item.id}/editar/', {'titulo': 'x', 'formato': 'reels'})
        self.item.refresh_from_db()
        self.assertEqual(self.item.titulo, 'Post de outubro')

    def test_comentario_vazio_ou_longo_e_recusado(self):
        self.assertEqual(self.client.post(self.url, {'texto': '   '}).status_code, 400)
        self.assertEqual(self.client.post(self.url, {'texto': 'a' * 2001}).status_code, 400)
        self.assertFalse(self.item.comentarios.exists())

    def test_cada_pessoa_apaga_so_o_proprio_comentario(self):
        from .models import ComentarioItemAgenda
        do_admin = ComentarioItemAgenda.objects.create(item=self.item, autor=self.admin, autor_nome='Miron', texto='a')
        self.client.force_login(self.cliente)
        self.client.get('/dashboard/')
        self.assertEqual(self.client.post(f'/programacao/comentarios/{do_admin.id}/excluir/').status_code, 404)
        meu = self.client.post(self.url, {'texto': 'b'}).json()['comentario']
        self.assertEqual(self.client.post(meu['excluir']).status_code, 200)
        self.assertEqual(list(self.item.comentarios.values_list('texto', flat=True)), ['a'])

    def test_outra_conta_nao_ve_nem_comenta(self):
        from django.contrib.auth.models import User
        from .models import Perfil
        estranho = User.objects.create_user('estranho', password='x')
        Perfil.objects.create(usuario=estranho, conta=estranho, papel=Perfil.ADMIN)
        self.client.post(self.url, {'texto': 'interno'})
        self.client.force_login(estranho)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, {'texto': 'oi'}).status_code, 404)
        self.assertEqual(self.item.comentarios.count(), 1)

    def test_nome_fica_no_comentario_se_o_usuario_for_removido(self):
        self.client.force_login(self.cliente)
        self.client.post(self.url, {'texto': 'Ficou ótimo'})
        self.cliente.delete()
        self.client.force_login(self.admin)
        comentario = self.client.get(self.url).json()['comentarios'][0]
        self.assertEqual((comentario['autor'], comentario['meu']), ('Cliente', False))

    def test_janela_tem_os_comentarios_e_o_item_mostra_quantos(self):
        self.client.post(self.url, {'texto': 'um'})
        self.client.post(self.url, {'texto': 'dois'})
        pagina = self.client.get('/programacao/', {'mes': '2026-10', 'dia': '2026-10-01'})
        self.assertContains(pagina, f'data-comentarios="{self.url}"')
        self.assertContains(pagina, 'id="itemChat"')
        self.assertContains(pagina, '2 comentários')
        self.item.delete()
        from .models import ComentarioItemAgenda
        self.assertFalse(ComentarioItemAgenda.objects.exists())


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class LandingTests(TestCase):
    def test_landing_abre_sem_login_com_whatsapp_e_entrar(self):
        resp = self.client.get('/plataforma/')
        self.assertEqual(resp.status_code, 200)
        whatsapp = 'https://wa.me/556293676291?text=Ol%C3%A1%2C%20gostaria%20de%20saber%20mais%20sobre%20a%20plataforma'
        self.assertContains(resp, f'href="{whatsapp}"', count=3)  # menu Contato, apresentação e botão flutuante
        self.assertContains(resp, '<a href="/" class="lp-btn lp-btn--neon lp-btn--pequeno">', count=1)
        self.assertContains(resp, 'Para quem vive de Rede social')
        self.assertNotContains(resp, 'Quer ver o Nextsora funcionando')
        self.assertContains(resp, 'href="/privacidade/"')


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class NovidadeTests(TestCase):
    def test_aviso_da_nova_tela_de_publico_aparece_fora_da_propria_tela(self):
        from django.contrib.auth.models import User
        self.client.force_login(User.objects.get(username='mironlucas'))
        for pagina in ('/dashboard/', '/programacao/', '/tarefas/'):
            resp = self.client.get(pagina)
            self.assertContains(resp, 'data-chave="nextsora:novidade:publico-2026-10"')
            self.assertContains(resp, 'A aba Público está de cara nova')
            self.assertContains(resp, 'href="/publico/" class="btn-primary btn-sm novidade-ir"')
        self.assertNotContains(self.client.get('/publico/'), 'id="novidade"')
        self.client.logout()
        self.assertNotContains(self.client.get('/'), 'id="novidade"')  # tela de login
